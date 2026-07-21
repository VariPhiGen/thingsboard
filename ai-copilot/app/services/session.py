from __future__ import annotations

import logging
import time
from uuid import UUID

from app.config import Settings
from app.models.schemas import (
    AlarmInfo,
    ChatRequest,
    ChatResponse,
    DeviceInfo,
    DeviceSnapshot,
    Intent,
    TbUser,
)
from app.services.device_resolver import DeviceResolver
from app.services.intent import IntentClassifier
from app.services.llm import LlmService
from app.services.memory import ConversationMemory, RateLimiter
from app.services.permissions import PermissionManager
from app.services.prompt_builder import build_messages
from app.services.rag import RagService
from app.services.tb_client import ThingsBoardClient
from app.services.tools.reports import format_report_context, load_latest_report_summary
from app.services.tools.telemetry import fetch_active_alarms, fetch_ai_scores, fetch_history, fetch_latest_snapshot

log = logging.getLogger(__name__)

FALLBACK = (
    "I could not finish that answer just now. "
    "Please retry, or check the device live readings and alarm widgets on the dashboard."
)
UNSUPPORTED = (
    "I can help with live device status, alarms, AI guidance, history, and procedures, "
    "but I cannot share secrets or make configuration changes."
)


class CopilotOrchestrator:
    def __init__(self, settings: Settings, memory: ConversationMemory, rag: RagService):
        self.settings = settings
        self.memory = memory
        self.rag = rag
        self.resolver = DeviceResolver()
        self.intent_clf = IntentClassifier()
        self.perms = PermissionManager()
        self.rate_limiter = RateLimiter(settings)
        self.llm = LlmService(settings)

    async def list_devices(self, token: str) -> list[DeviceInfo]:
        client = ThingsBoardClient(self.settings, token)
        return await self.perms.list_accessible_devices(client)

    async def chat(self, user: TbUser, token: str, request: ChatRequest) -> ChatResponse:
        conversation_id = self.memory.ensure_conversation_id(request.conversationId)
        intent = self.intent_clf.classify(request.message)

        try:
            self.rate_limiter.check(user.id, request.deviceId)
        except RuntimeError as exc:
            return ChatResponse(
                conversationId=conversation_id,
                answer=str(exc),
                timestamp=int(time.time() * 1000),
                intent=intent,
                sources=[],
            )

        if intent == Intent.UNSUPPORTED_SECRETS:
            self.memory.append(conversation_id, "USER", request.message)
            self.memory.append(conversation_id, "ASSISTANT", UNSUPPORTED)
            return ChatResponse(
                conversationId=conversation_id,
                answer=UNSUPPORTED,
                timestamp=int(time.time() * 1000),
                intent=intent,
                sources=[],
            )

        client = ThingsBoardClient(self.settings, token)
        devices = await self.perms.list_accessible_devices(client)
        resolved = self.resolver.resolve(
            devices,
            device_id=request.deviceId,
            device_query=request.deviceQuery,
            message=request.message,
        )

        if resolved.needs_clarification or resolved.device is None:
            names = ", ".join(d.name for d in resolved.candidates[:8]) or "no accessible devices"
            answer = f"{resolved.reason or 'Please choose a device.'} Available: {names}."
            self.memory.append(conversation_id, "USER", request.message)
            self.memory.append(conversation_id, "ASSISTANT", answer)
            return ChatResponse(
                conversationId=conversation_id,
                answer=answer,
                timestamp=int(time.time() * 1000),
                intent=Intent.CLARIFY_DEVICE,
                sources=["device catalog"],
                resolvedDevice=None,
            )

        device = resolved.device
        sources: list[str] = []
        snapshot = None
        alarms: list[AlarmInfo] = []
        grounding_parts: list[str] = [f"Device: {device.name} ({device.id})"]

        try:
            await self.perms.ensure_device_access(client, device.id)

            if intent in {Intent.STATUS, Intent.GENERAL, Intent.AI_GUIDANCE, Intent.ALARMS, Intent.HISTORY, Intent.COMPARE_DEVICES}:
                snap = await fetch_latest_snapshot(client, device.id, device.name, device.type)
                snapshot = DeviceSnapshot(
                    deviceName=snap["deviceName"],
                    lastTelemetryTs=snap.get("lastTelemetryTs"),
                    values=snap.get("values") or {},
                )
                grounding_parts.append("Latest telemetry:\n" + "\n".join(f"- {k}: {v}" for k, v in snapshot.values.items()))
                sources.append("telemetry")

            if intent in {Intent.ALARMS, Intent.STATUS, Intent.GENERAL, Intent.AI_GUIDANCE}:
                raw_alarms = await fetch_active_alarms(client, device.id)
                alarms = [AlarmInfo(**a) for a in raw_alarms]
                if alarms:
                    grounding_parts.append(
                        "Active alarms:\n"
                        + "\n".join(f"- [{a.severity}] {a.type}: {a.details or a.status}" for a in alarms)
                    )
                else:
                    grounding_parts.append("Active alarms: none")
                sources.append("alarms")

            if intent in {Intent.AI_GUIDANCE, Intent.GENERAL, Intent.STATUS}:
                scores = await fetch_ai_scores(client, device.id)
                if scores:
                    grounding_parts.append("AI scores:\n" + "\n".join(f"- {k}: {v}" for k, v in scores.items()))
                    sources.append("AI scores")

            if intent == Intent.HISTORY:
                end_ts = int(time.time() * 1000)
                start_ts = end_ts - 24 * 3600 * 1000
                hist = await fetch_history(client, device.id, device.name, start_ts, end_ts)
                grounding_parts.append("24h history summary:\n" + str(hist))
                sources.append("history")

            if intent in {Intent.COMPARE_DEVICES, Intent.GENERAL, Intent.MANUAL_HOWTO, Intent.AI_GUIDANCE}:
                report = load_latest_report_summary(self.settings.reports_dir)
                grounding_parts.append(format_report_context(report))
                if report:
                    sources.append("reports")

        except PermissionError as exc:
            answer = f"Access denied for device {device.name}: {exc}"
            return ChatResponse(
                conversationId=conversation_id,
                answer=answer,
                timestamp=int(time.time() * 1000),
                intent=intent,
                sources=sources,
                resolvedDevice=device,
            )
        except Exception as exc:
            log.exception("tooling failed: %s", exc)
            grounding_parts.append(f"Tooling warning: {exc}")

        rag_query = request.message
        if intent == Intent.MANUAL_HOWTO:
            rag_query = f"operator manual SOP {device.name} {request.message}"
        snippets = self.rag.retrieve(rag_query)
        rag_text = self.rag.format_snippets(snippets)
        if snippets:
            sources.extend(f"rag:{s.get('source')}" for s in snippets)

        history = self.memory.get_messages(conversation_id)
        # Avoid duplicating current user turn if client already sent history
        msgs = build_messages(
            intent=intent,
            user_message=request.message,
            history=history,
            grounding="\n\n".join(grounding_parts),
            rag_snippets=rag_text,
        )

        try:
            answer = await self.llm.complete(msgs)
            if not answer:
                answer = FALLBACK
        except Exception as exc:
            log.exception("llm failed: %s", exc)
            answer = FALLBACK

        self.memory.append(conversation_id, "USER", request.message)
        self.memory.append(conversation_id, "ASSISTANT", answer)

        return ChatResponse(
            conversationId=conversation_id,
            answer=answer,
            timestamp=int(time.time() * 1000),
            resolvedDevice=device,
            intent=intent,
            sources=list(dict.fromkeys(sources)),
            deviceSnapshot=snapshot,
            activeAlarms=alarms,
        )
