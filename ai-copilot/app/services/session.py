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
from app.services.tools.telemetry import fetch_active_alarms, fetch_ai_scores, fetch_latest_snapshot
from app.services.tools.analytics import (
    analyze_window,
    compare_devices,
    compare_periods,
    fetch_window_series,
)
from app.services.time_window import TimeWindow, parse_time_window

log = logging.getLogger(__name__)

FALLBACK = (
    "I could not finish that answer just now. "
    "Please retry, or check the device live readings and alarm widgets on the dashboard."
)
UNSUPPORTED = (
    "I can help with live status, alarms, AI guidance, procedures, "
    "and time/date/shift/duration/statistics/trend/comparison analysis, "
    "but I cannot share secrets or make configuration changes."
)

ANALYTICS_INTENTS = {
    Intent.HISTORY,
    Intent.TIME_BASED,
    Intent.DATE_BASED,
    Intent.SHIFT_BASED,
    Intent.DURATION_BASED,
    Intent.STATISTICS,
    Intent.TREND,
    Intent.COMPARISON,
}


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

            if intent in {Intent.STATUS, Intent.GENERAL, Intent.AI_GUIDANCE, Intent.ALARMS, Intent.COMPARE_DEVICES} | ANALYTICS_INTENTS:
                snap = await fetch_latest_snapshot(client, device.id, device.name, device.type)
                snapshot = DeviceSnapshot(
                    deviceName=snap["deviceName"],
                    lastTelemetryTs=snap.get("lastTelemetryTs"),
                    values=snap.get("values") or {},
                )
                grounding_parts.append("Latest live readings:\n" + "\n".join(f"- {k}: {v}" for k, v in snapshot.values.items()))
                sources.append("live readings")

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

            if intent in ANALYTICS_INTENTS:
                window = parse_time_window(request.message)
                mode = {
                    Intent.TIME_BASED: "time",
                    Intent.DATE_BASED: "date",
                    Intent.SHIFT_BASED: "shift",
                    Intent.DURATION_BASED: "duration",
                    Intent.STATISTICS: "statistics",
                    Intent.TREND: "trend",
                    Intent.COMPARISON: "comparison",
                    Intent.HISTORY: "time",
                }.get(intent, "general")

                if intent == Intent.COMPARISON:
                    # Compare previous equivalent window vs current window when user says vs yesterday/last week
                    lower = request.message.lower()
                    if "yesterday" in lower and "today" in lower:
                        today = parse_time_window("today")
                        yday = parse_time_window("yesterday")
                        grounding_parts.append(
                            await compare_periods(
                                client, device.id, device.name, request.message, yday, today, device.type
                            )
                        )
                    else:
                        # default: previous equal-length period vs current window
                        span = max(1, window.end_ts - window.start_ts)
                        prev = TimeWindow(
                            start_ts=window.start_ts - span,
                            end_ts=window.start_ts,
                            label=f"previous period before {window.label}",
                            kind="relative",
                        )
                        grounding_parts.append(
                            await compare_periods(
                                client, device.id, device.name, request.message, prev, window, device.type
                            )
                        )
                else:
                    series_payload = await fetch_window_series(
                        client, device.id, device.name, window, request.message, device.type
                    )
                    grounding_parts.append(analyze_window(device.name, window, series_payload, mode))
                sources.append("history analysis")

            if intent == Intent.COMPARE_DEVICES:
                window = parse_time_window(request.message)
                # compare selected device with up to 2 peers
                peers = [(device.id, device.name, device.type)]
                for d in devices:
                    if d.id == device.id:
                        continue
                    peers.append((d.id, d.name, d.type))
                    if len(peers) >= 3:
                        break
                grounding_parts.append(await compare_devices(client, peers, request.message, window))
                sources.append("device comparison")

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
