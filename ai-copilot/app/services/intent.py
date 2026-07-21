from __future__ import annotations

import re

from app.models.schemas import Intent

SECRET_RE = re.compile(
    r"\b(api[_\s-]?key|secret|password|token|credential|private[_\s-]?key)\b|"
    r"\b(change|update|modify|delete|write)\b.*\b(config|configuration|rule\s*chain|credential)\b",
    re.I,
)


class IntentClassifier:
    def classify(self, message: str) -> Intent:
        text = (message or "").strip()
        if not text:
            return Intent.GENERAL
        if SECRET_RE.search(text):
            return Intent.UNSUPPORTED_SECRETS

        lower = text.lower()
        if any(k in lower for k in ("manual", "how do i", "how to", "sop", "procedure", "steps to")):
            return Intent.MANUAL_HOWTO
        if any(k in lower for k in ("compare", "both devices", "all devices", "which device", "fleet")):
            return Intent.COMPARE_DEVICES
        if any(k in lower for k in ("alarm", "alert", "fault", "trip")):
            return Intent.ALARMS
        if any(k in lower for k in ("history", "trend", "last hour", "last 24", "yesterday", "over time")):
            return Intent.HISTORY
        if any(k in lower for k in ("ai ", "summary", "recommendation", "rul", "health score", "failure risk", "guidance")):
            return Intent.AI_GUIDANCE
        if any(k in lower for k in ("status", "running", "offline", "rpm", "power", "oil", "coolant", "fuel", "battery")):
            return Intent.STATUS
        return Intent.GENERAL
