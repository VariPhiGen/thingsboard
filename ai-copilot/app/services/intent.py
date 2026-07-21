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

        # Shift before generic time, because "morning shift today" is shift-based
        if any(k in lower for k in ("shift", "morning shift", "afternoon shift", "night shift", "a shift", "b shift", "c shift")):
            return Intent.SHIFT_BASED

        if any(k in lower for k in ("compare", "vs", "versus", "difference between", "both devices", "all devices", "fleet")):
            if "device" in lower or "dg" in lower or "gateway" in lower or "fleet" in lower or "both" in lower:
                return Intent.COMPARE_DEVICES
            return Intent.COMPARISON

        if any(k in lower for k in ("trend", "trending", "rising", "falling", "increasing", "decreasing", "over time")):
            return Intent.TREND

        if any(k in lower for k in ("average", "avg", "mean", "min", "max", "minimum", "maximum", "statistics", "stats", "median")):
            return Intent.STATISTICS

        if any(k in lower for k in ("how long", "duration", "running hours", "run hours", "uptime", "downtime", "time running")):
            return Intent.DURATION_BASED

        if any(k in lower for k in ("yesterday", "today", "this week", "date", "on 20", "on 202")) or re.search(
            r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b", lower
        ):
            return Intent.DATE_BASED

        if any(
            k in lower
            for k in (
                "last hour",
                "last 24",
                "last day",
                "last week",
                "past hour",
                "past 24",
                "minutes",
                "hours",
                "history",
            )
        ) or re.search(r"last\s+\d+\s*(min|minute|minutes|hour|hours|hr|hrs|day|days)\b", lower):
            return Intent.TIME_BASED

        if any(k in lower for k in ("alarm", "alert", "fault", "trip")):
            return Intent.ALARMS
        if any(k in lower for k in ("ai ", "summary", "recommendation", "rul", "health score", "failure risk", "guidance")):
            return Intent.AI_GUIDANCE
        if any(k in lower for k in ("status", "running", "offline", "rpm", "power", "oil", "coolant", "fuel", "battery")):
            return Intent.STATUS
        return Intent.GENERAL
