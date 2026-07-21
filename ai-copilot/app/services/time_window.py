from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Plant shifts (IST)
SHIFTS = {
    "morning": (6, 14),
    "a": (6, 14),
    "afternoon": (14, 22),
    "evening": (14, 22),
    "b": (14, 22),
    "night": (22, 6),
    "c": (22, 6),
}


@dataclass
class TimeWindow:
    start_ts: int
    end_ts: int
    label: str
    kind: str  # time|date|shift|duration|relative


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_time_window(message: str, now: datetime | None = None) -> TimeWindow:
    """Parse operator natural language into an IST-based analysis window."""
    text = (message or "").lower()
    now = now or now_ist()
    end = now

    # Duration phrases still need a lookback window for sampling
    if m := re.search(r"last\s+(\d+)\s*(minute|minutes|min|mins)\b", text):
        n = int(m.group(1))
        start = end - timedelta(minutes=n)
        return TimeWindow(_ms(start), _ms(end), f"last {n} minutes", "time")

    if m := re.search(r"last\s+(\d+)\s*(hour|hours|hr|hrs)\b", text):
        n = int(m.group(1))
        start = end - timedelta(hours=n)
        return TimeWindow(_ms(start), _ms(end), f"last {n} hours", "time")

    if m := re.search(r"last\s+(\d+)\s*(day|days)\b", text):
        n = int(m.group(1))
        start = end - timedelta(days=n)
        return TimeWindow(_ms(start), _ms(end), f"last {n} days", "time")

    if "last hour" in text or "past hour" in text:
        start = end - timedelta(hours=1)
        return TimeWindow(_ms(start), _ms(end), "last 1 hour", "time")

    if "last 24" in text or "past 24" in text or "last day" in text:
        start = end - timedelta(hours=24)
        return TimeWindow(_ms(start), _ms(end), "last 24 hours", "time")

    if "yesterday" in text:
        day = (now - timedelta(days=1)).date()
        start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=IST)
        end_d = start + timedelta(days=1)
        return TimeWindow(_ms(start), _ms(end_d), f"yesterday ({day.isoformat()})", "date")

    if "today" in text or "this date" in text:
        day = now.date()
        start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=IST)
        return TimeWindow(_ms(start), _ms(end), f"today ({day.isoformat()})", "date")

    if "this week" in text:
        day = now.date()
        start_day = day - timedelta(days=day.weekday())
        start = datetime(start_day.year, start_day.month, start_day.day, 0, 0, tzinfo=IST)
        return TimeWindow(_ms(start), _ms(end), "this week", "date")

    # Explicit date: 2026-07-20 or 20/07/2026 or 20-07-2026
    if m := re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = datetime(y, mo, d, 0, 0, tzinfo=IST)
        end_d = start + timedelta(days=1)
        return TimeWindow(_ms(start), _ms(end_d), f"date {start.date().isoformat()}", "date")
    if m := re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = datetime(y, mo, d, 0, 0, tzinfo=IST)
        end_d = start + timedelta(days=1)
        return TimeWindow(_ms(start), _ms(end_d), f"date {start.date().isoformat()}", "date")

    # Shift based
    shift_name = None
    for key in ("morning", "afternoon", "evening", "night"):
        if key in text:
            shift_name = key
            break
    if shift_name is None:
        if re.search(r"\bshift\s*a\b", text) or re.search(r"\ba\s*shift\b", text):
            shift_name = "a"
        elif re.search(r"\bshift\s*b\b", text) or re.search(r"\bb\s*shift\b", text):
            shift_name = "b"
        elif re.search(r"\bshift\s*c\b", text) or re.search(r"\bc\s*shift\b", text):
            shift_name = "c"
        elif "shift" in text:
            # current shift by clock
            hour = now.hour
            if 6 <= hour < 14:
                shift_name = "morning"
            elif 14 <= hour < 22:
                shift_name = "afternoon"
            else:
                shift_name = "night"

    if shift_name:
        start_h, end_h = SHIFTS[shift_name]
        day = now.date()
        if "yesterday" in text:
            day = (now - timedelta(days=1)).date()
        start = datetime(day.year, day.month, day.day, start_h, 0, tzinfo=IST)
        if end_h > start_h:
            end_s = datetime(day.year, day.month, day.day, end_h, 0, tzinfo=IST)
        else:
            # night shift crosses midnight
            end_s = datetime(day.year, day.month, day.day, end_h, 0, tzinfo=IST) + timedelta(days=1)
            if now.hour < end_h and "yesterday" not in text:
                # currently in early morning part of night shift that started previous day
                start = start - timedelta(days=1)
                end_s = datetime(day.year, day.month, day.day, end_h, 0, tzinfo=IST)
        # clamp end to now for current shift
        if end_s > now and "yesterday" not in text:
            end_s = now
        label = f"{shift_name} shift ({start.strftime('%Y-%m-%d %H:%M')} to {end_s.strftime('%Y-%m-%d %H:%M')} IST)"
        return TimeWindow(_ms(start), _ms(end_s), label, "shift")

    # Default: last 24 hours
    start = end - timedelta(hours=24)
    return TimeWindow(_ms(start), _ms(end), "last 24 hours", "relative")


METRIC_ALIASES = {
    "power": "power_kw",
    "kw": "power_kw",
    "load": "power_kw",
    "rpm": "engine_rpm",
    "engine rpm": "engine_rpm",
    "speed": "engine_rpm",
    "oil": "oil_pressure",
    "oil pressure": "oil_pressure",
    "coolant": "coolant_temp",
    "temperature": "coolant_temp",
    "temp": "coolant_temp",
    "fuel": "fuel_level",
    "battery": "battery_voltage",
    "voltage": "battery_voltage",
    "frequency": "frequency",
    "hz": "frequency",
    "health": "health_score",
    "risk": "failure_risk_pct",
}


def extract_metric_keys(message: str, fallback_keys: list[str]) -> list[str]:
    text = (message or "").lower()
    found: list[str] = []
    for alias, key in sorted(METRIC_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in text and key not in found:
            found.append(key)
    if found:
        return found
    # sensible defaults for analytics
    defaults = [k for k in ("power_kw", "engine_rpm", "coolant_temp", "oil_pressure", "fuel_level") if k in fallback_keys]
    return defaults or fallback_keys[:5]
