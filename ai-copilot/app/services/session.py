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
from app.services.prompt_builder import build_messages, detect_language
from app.services.rag import RagService
from app.services.tb_client import ThingsBoardClient
from app.services.tools.reports import format_report_context, load_latest_report_summary
from app.services.tools.telemetry import (
    fetch_active_alarms,
    fetch_ai_scores,
    fetch_fleet_overview,
    fetch_latest_snapshot,
)
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
    "and time/date/shift/duration/statistics/trend/comparison analysis across all plant devices, "
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

        if intent in {Intent.GREETING, Intent.IDENTITY}:
            lang = detect_language(request.message)
            if intent == Intent.GREETING:
                answer = self._generate_greeting_response(lang=lang)
            else:
                answer = self._generate_identity_response(lang=lang)
            self.memory.append(conversation_id, "USER", request.message)
            self.memory.append(conversation_id, "ASSISTANT", answer)
            return ChatResponse(
                conversationId=conversation_id,
                answer=answer,
                timestamp=int(time.time() * 1000),
                intent=intent,
                sources=["virtuoso_copilot_identity"],
                resolvedDevice=None,
            )

        client = ThingsBoardClient(self.settings, token)
        devices = await self.perms.list_accessible_devices(client)
        resolved = self.resolver.resolve(
            devices,
            device_id=request.deviceId,
            device_query=request.deviceQuery,
            dashboard_id=request.dashboardId,
            message=request.message,
        )

        # -------------------------------------------------------------
        # CASE 1: Fleet-wide / Multi-device / General Plant Query
        # -------------------------------------------------------------
        if resolved.is_fleet:
            sources: list[str] = ["fleet telemetry", "live readings", "alarms"]
            fleet_data = await fetch_fleet_overview(client, devices)

            grounding_parts: list[str] = [
                "Facility Equipment Overview (All 7 Live Systems):"
            ]
            total_active_alarms = 0
            for dev in fleet_data:
                d_name = dev["name"]
                d_type = dev.get("type", "")
                vals = dev.get("values", {})
                d_alarms = dev.get("alarms", [])
                total_active_alarms += len(d_alarms)

                reading_lines = [f"{k}: {v}" for k, v in list(vals.items())[:8]]
                readings_str = "; ".join(reading_lines) if reading_lines else "Standby / No active values"
                alarm_str = f"{len(d_alarms)} ACTIVE ALARM(S)" if d_alarms else "Normal (No alarms)"

                grounding_parts.append(
                    f"• {d_name} (Profile: {d_type})\n"
                    f"  Alarms: {alarm_str}\n"
                    f"  Telemetry: {readings_str}"
                )

            report = load_latest_report_summary(self.settings.reports_dir)
            if report:
                grounding_parts.append(format_report_context(report))
                sources.append("reports")

            snippets = self.rag.retrieve(request.message)
            rag_text = self.rag.format_snippets(snippets)
            if snippets:
                sources.extend(f"rag:{s.get('source')}" for s in snippets)

            history = self.memory.get_messages(conversation_id)
            msgs = build_messages(
                intent=intent,
                user_message=request.message,
                history=history,
                grounding="\n\n".join(grounding_parts),
                rag_snippets=rag_text,
            )

            lang = detect_language(request.message)
            try:
                answer = await self.llm.complete(msgs)
                if not answer:
                    answer = self._generate_fleet_fallback(fleet_data, lang=lang)
            except Exception as exc:
                log.warning("LLM fleet query failed: %s", exc)
                answer = self._generate_fleet_fallback(fleet_data, error_hint=str(exc), lang=lang)

            self.memory.append(conversation_id, "USER", request.message)
            self.memory.append(conversation_id, "ASSISTANT", answer)

            return ChatResponse(
                conversationId=conversation_id,
                answer=answer,
                timestamp=int(time.time() * 1000),
                intent=Intent.GENERAL,
                sources=list(dict.fromkeys(sources)),
                resolvedDevice=None,
            )

        # -------------------------------------------------------------
        # CASE 2: Ambiguous device mention requiring clarification
        # -------------------------------------------------------------
        if resolved.needs_clarification or resolved.device is None:
            lang = detect_language(request.message)
            lines = []
            for i, d in enumerate(resolved.candidates[:12], start=1):
                lines.append(f"{i}. {d.name}")
            listed = "\n".join(lines) if lines else "No accessible devices."
            if lang == "en":
                answer = (
                    f"{resolved.reason or 'Which device would you like to inquire about?'}\n\n"
                    f"Available Facility Systems:\n{listed}\n\n"
                    "You can type the device name or number (e.g. 1, 2) to continue."
                )
            else:
                answer = (
                    f"{resolved.reason or 'Aap kis device ke baare me puchna chahte hain?'}\n\n"
                    f"Available Facility Systems:\n{listed}\n\n"
                    "Aap number (jaise 1, 2) ya device ka naam type karke puch sakte hain."
                )
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

        # -------------------------------------------------------------
        # CASE 3: Single Device Query
        # -------------------------------------------------------------
        device = resolved.device
        sources: list[str] = []
        snapshot = None
        alarms: list[AlarmInfo] = []
        grounding_parts: list[str] = [f"Device: {device.name} ({device.id}) [Profile: {device.type}]"]

        try:
            await self.perms.ensure_device_access(client, device.id)

            if intent in {Intent.STATUS, Intent.GENERAL, Intent.AI_GUIDANCE, Intent.ALARMS, Intent.COMPARE_DEVICES} | ANALYTICS_INTENTS:
                snap = await fetch_latest_snapshot(client, device.id, device.name, device.type)
                snapshot = DeviceSnapshot(
                    deviceName=snap["deviceName"],
                    lastTelemetryTs=snap.get("lastTelemetryTs"),
                    values=snap.get("values") or {},
                )
                grounding_parts.append(
                    "Latest live readings:\n" + "\n".join(f"- {k}: {v}" for k, v in snapshot.values.items())
                )
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
                if report:
                    grounding_parts.append(format_report_context(report))
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
            grounding_parts.append(f"Tooling note: {exc}")

        rag_query = request.message
        if intent == Intent.MANUAL_HOWTO:
            rag_query = f"operator manual SOP {device.name} {request.message}"
        snippets = self.rag.retrieve(rag_query)
        rag_text = self.rag.format_snippets(snippets)
        if snippets:
            sources.extend(f"rag:{s.get('source')}" for s in snippets)

        history = self.memory.get_messages(conversation_id)
        msgs = build_messages(
            intent=intent,
            user_message=request.message,
            history=history,
            grounding="\n\n".join(grounding_parts),
            rag_snippets=rag_text,
        )

        lang = detect_language(request.message)
        try:
            answer = await self.llm.complete(msgs)
            if not answer:
                answer = self._generate_grounded_fallback(intent, device, snapshot, alarms, lang=lang)
        except Exception as exc:
            log.warning("llm failed: %s", exc)
            err_str = str(exc)
            hint = None
            if "401" in err_str or "invalid" in err_str.lower():
                hint = "LLM API Key authorization invalid"
            elif "429" in err_str or "quota" in err_str.lower():
                hint = "LLM Rate limit / quota reached"
            answer = self._generate_grounded_fallback(intent, device, snapshot, alarms, error_hint=hint, lang=lang)

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

    def _generate_fleet_fallback(self, fleet_data: list[dict[str, Any]], error_hint: str | None = None, lang: str = "en") -> str:
        if lang == "en":
            lines = [
                "Hello! Here is the live status overview for all 7 facility systems:\n",
            ]
        else:
            lines = [
                "Namaste! Delhivery Facility ke sabhi 7 systems ka live status overview yeh raha:\n",
            ]
        
        dg_lines = []
        lt_lines = []
        ro_lines = []
        fire_lines = []

        for d in fleet_data:
            name = d["name"]
            vals = d.get("values", {})
            alarms = d.get("alarms", [])
            has_alarms = len(alarms) > 0
            icon = "🔴" if has_alarms else "🟢"
            
            summary_items = []
            for k, v in list(vals.items())[:3]:
                summary_items.append(f"{k}: {v}")
            summary_str = " | ".join(summary_items) if summary_items else ("Standby (Normal)" if lang == "en" else "Standby (Normal)")
            
            entry = f"- {icon} **{name}**: {summary_str}"
            if has_alarms:
                entry += f" *(⚠️ {len(alarms)} Alarms Active)*"

            lower = name.lower()
            if "dg" in lower:
                dg_lines.append(entry)
            elif "lt" in lower or "panel" in lower:
                lt_lines.append(entry)
            elif "ro" in lower:
                ro_lines.append(entry)
            elif "fire" in lower or "suppression" in lower:
                fire_lines.append(entry)
            else:
                dg_lines.append(entry)

        if dg_lines:
            lines.append("⚡ **DG Sets (Woodward KG1500):**")
            lines.extend(dg_lines)
            lines.append("")

        if lt_lines:
            lines.append("🔌 **Power & LT Panels:**")
            lines.extend(lt_lines)
            lines.append("")

        if ro_lines:
            lines.append("💧 **Water Treatment (RO Plant):**")
            lines.extend(ro_lines)
            lines.append("")

        if fire_lines:
            lines.append("🧯 **Fire Suppression Systems:**")
            lines.extend(fire_lines)
            lines.append("")

        if lang == "en":
            lines.append("💡 *You can type any machine name (e.g. 'RO Plant TDS' or 'DG 1 status') for detailed readings.*")
        else:
            lines.append("💡 *Aap kisi bhi machine ka naam (jaise 'RO Plant ka TDS' ya 'DG 1') likhkar detail me pooch sakte hain.*")
        return "\n".join(lines)

    def _generate_grounded_fallback(
        self,
        intent: Intent,
        device: DeviceInfo,
        snapshot: DeviceSnapshot | None,
        alarms: list[AlarmInfo],
        error_hint: str | None = None,
        lang: str = "en",
    ) -> str:
        if lang == "en":
            parts: list[str] = [f"Hello! Here is the live status report for **{device.name}**:\n"]
            if alarms:
                parts.append("⚠️ **Active Alarms & Alerts:**")
                for a in alarms:
                    sev_icon = "🔴" if (a.severity or "").upper() == "CRITICAL" else "🟡"
                    detail_str = f" — {a.details}" if a.details else ""
                    parts.append(f"- {sev_icon} **{a.type}** [{a.severity or 'ALERT'}]{detail_str}")
                parts.append("Please inspect active alarms and follow standard operating procedures.\n")
            else:
                parts.append("🟢 **Alert Status:** No active alarms. All parameters are within safe limits.\n")

            if snapshot and snapshot.values:
                parts.append("📊 **Current Live Telemetry:**")
                for k, v in list(snapshot.values.items())[:12]:
                    parts.append(f"• **{k}:** {v}")
                parts.append("")
            else:
                parts.append("*(Machine is in standby or live telemetry is synchronizing)*\n")

            parts.append("💡 *Feel free to ask about any specific reading, history trend, or maintenance SOP.*")
        else:
            parts: list[str] = [f"Namaste! **{device.name}** ka live status report yeh raha:\n"]
            if alarms:
                parts.append("⚠️ **Active Alarms & Alerts:**")
                for a in alarms:
                    sev_icon = "🔴" if (a.severity or "").upper() == "CRITICAL" else "🟡"
                    detail_str = f" — {a.details}" if a.details else ""
                    parts.append(f"- {sev_icon} **{a.type}** [{a.severity or 'ALERT'}]{detail_str}")
                parts.append("Kripya alarms check karein aur standard operating procedure follow karein.\n")
            else:
                parts.append("🟢 **Alert Status:** Koi active alarm nahi hai. Sabhi parameters safe limit me hain.\n")

            if snapshot and snapshot.values:
                parts.append("📊 **Current Live Telemetry:**")
                for k, v in list(snapshot.values.items())[:12]:
                    parts.append(f"• **{k}:** {v}")
                parts.append("")
            else:
                parts.append("*(Machine standby me hai ya live telemetry synchronize ho rahi hai)*\n")

            parts.append("💡 *Aap kisi specific reading, past history ya maintenance SOP ke baare me pooch sakte hain.*")
        return "\n".join(parts)

    def _generate_greeting_response(self, lang: str = "en") -> str:
        if lang == "en":
            return (
                "Hello! 👋 Welcome to **Virtuoso AI Copilot** — your real-time intelligence assistant for Delhivery Facility Operations.\n\n"
                "I am here to assist you with live equipment monitoring, real-time telemetry, active alarms, and operational diagnostics across all facility systems:\n\n"
                "• ⚡ **DG Sets (DG 1, DG 2, DG 3)**: Active power (kW), RPM, fuel level, battery voltage, coolant temperature, and operational state.\n"
                "• 💧 **RO Water Plant**: Real-time TDS (ppm), permeate flow rate, operating pressure, and water quality analysis.\n"
                "• 🔌 **LT Electrical Panels**: Live load, current, and voltage across Transformers (1-3), Electrical Rooms, UPS panels, and EV chargers.\n"
                "• 🧯 **Fire Suppression**: Monitored gas cylinder pressures in the Main Room and UPS Room 2.\n"
                "• 🚨 **Active Alarms & SOPs**: Instant safety alerts, root-cause diagnostics, and emergency procedures.\n\n"
                "How can I assist you with the facility today? Feel free to ask about any specific machine or current readings!"
            )
        else:
            return (
                "Namaste! 🙏 **Virtuoso AI Copilot** me aapka swagat hai — Delhivery facility operations ke liye aapka smart industrial assistant.\n\n"
                "Aap mujhse facility ke sabhi equipment ka live data, telemetry, aur operational status jaan sakte hain:\n\n"
                "• ⚡ **DG Sets (DG 1, DG 2, DG 3)**: Live active power (kW), fuel level, battery voltage, temperature, aur operational status.\n"
                "• 💧 **RO Plant System**: Real-time TDS (ppm), water flow rate, operating pressure, aur water quality.\n"
                "• 🔌 **LT Panels Gateway**: Transformers aur electrical rooms ka live load, current, aur voltage.\n"
                "• 🧯 **Fire Suppression**: Main Fire Room aur UPS Room 2 ke gas cylinders ka live pressure monitoring.\n"
                "• 🚨 **Active Alarms**: Real-time alerts aur step-by-step troubleshooting SOPs.\n\n"
                "Bataiye, aaj main aapki kya madad kar sakta hoon?"
            )

    def _generate_identity_response(self, lang: str = "en") -> str:
        if lang == "en":
            return (
                "I am **Virtuoso AI Copilot**, an advanced industrial AI assistant developed by **Virtuoso NetSoft** specifically for **Delhivery's Facility Intelligence & Industrial IoT Operations**.\n\n"
                "### 🛠️ What I Do:\n"
                "I connect directly to your live IoT controllers and ThingsBoard telemetry streams to give facility operators, engineers, and plant managers instant, real-time insights:\n\n"
                "1. ⚡ **Diesel Generators (DG Set 1, 2, 3)**:\n"
                "   - Monitor live active power (kW), frequency (Hz), RPM, fuel level (%), battery voltage (V), coolant temperature, and oil pressure.\n"
                "   - Detect standby vs. running states immediately.\n\n"
                "2. 💧 **RO Water Purification Plant**:\n"
                "   - Live TDS (ppm), permeate flow rate (m³/h), operating pressure, and water quality diagnostics.\n\n"
                "3. 🔌 **LT Electrical Panels Gateway**:\n"
                "   - Real-time power load, voltage, current, and breaker status across 8 sub-panels (Transformers 1-3, Electrical Room, UPS panels, EVM chargers).\n\n"
                "4. 🧯 **Fire Suppression Systems**:\n"
                "   - Monitored cylinder pressures for FM-200 / Novec gas systems in Main Room and UPS Room 2.\n\n"
                "5. 🚨 **Active Alarms & Diagnostic Guidance**:\n"
                "   - Instant alarm detection with practical root-cause analysis and safety SOP steps.\n\n"
                "💬 **How to interact:**\n"
                "You can ask me anything in **English or Hindi** (e.g. *\"What is the Power Right Now in DG Set - 1 ?\"*, *\"RO Plant ka TDS kitna hai?\"*, or *\"Show fleet summary\"*). How can I assist you today?"
            )
        else:
            return (
                "Main **Virtuoso AI Copilot** hoon — ek advanced industrial AI assistant jise **Virtuoso NetSoft** ne Delhivery ke facility intelligence aur industrial IoT monitoring ke liye banaya hai.\n\n"
                "### 🛠️ Main Kya Kar Sakta Hoon:\n"
                "Main aapke ThingsBoard IoT controllers aur live sensor streams se directly connected hoon, jisse aapko facility ka instant real-time data milta hai:\n\n"
                "1. ⚡ **DG Sets (DG Set 1, 2, aur 3)**:\n"
                "   - Live Active Power (kW), fuel level (%), battery voltage, coolant temp, oil pressure, aur engine running/standby status.\n\n"
                "2. 💧 **RO Water Plant System**:\n"
                "   - Real-time TDS (ppm), permeate water flow rate, operating pressure, aur water quality analysis.\n\n"
                "3. 🔌 **LT Panels Gateway**:\n"
                "   - Transformers 1-3, Electrical Rooms, UPS panels, aur EVM chargers ka live load, voltage, aur current.\n\n"
                "4. 🧯 **Fire Suppression Systems**:\n"
                "   - Main Fire Room aur UPS Room 2 ke sabhi gas cylinders ka live pressure monitoring.\n\n"
                "5. 🚨 **Active Alarms & Safety SOPs**:\n"
                "   - Kisi bhi critical alert ka instant notification aur step-by-step troubleshooting guide.\n\n"
                "💬 Aap mujhse **English ya Hindi/Hinglish** dono me pooch sakte hain (jaise: *\"DG Set - 1 me abhi power kitna hai?\"*, *\"RO Plant TDS kitna hai?\"* ya *\"Sabhi systems ka summary do\"*). Bataiye, abhi aapko kis system ki jankari chahiye?"
            )
