"""Time window parser and metric extraction — all window kinds and edges."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.time_window import extract_metric_keys, parse_time_window

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=IST)  # Tuesday noon — morning shift already ended
NIGHT_NOW = datetime(2026, 7, 21, 2, 30, tzinfo=IST)  # early morning night shift
AFTERNOON_NOW = datetime(2026, 7, 21, 16, 0, tzinfo=IST)


def test_last_n_minutes():
    w = parse_time_window("last 15 minutes coolant", now=NOW)
    assert w.kind == "time"
    assert w.end_ts - w.start_ts == 15 * 60_000
    assert "15 minutes" in w.label


def test_last_n_hours():
    w = parse_time_window("last 3 hours", now=NOW)
    assert w.kind == "time"
    assert w.end_ts - w.start_ts == 3 * 3_600_000


def test_last_n_days():
    w = parse_time_window("last 2 days", now=NOW)
    assert w.kind == "time"
    assert w.end_ts - w.start_ts == 2 * 86_400_000


def test_last_hour_and_past_hour():
    for msg in ("last hour", "past hour power"):
        w = parse_time_window(msg, now=NOW)
        assert w.end_ts - w.start_ts == 3_600_000


def test_last_day_and_24h():
    for msg in ("last day status", "last 24 hours", "past 24 hrs"):
        w = parse_time_window(msg, now=NOW)
        assert w.end_ts - w.start_ts == 24 * 3_600_000


def test_yesterday_full_day():
    w = parse_time_window("power yesterday", now=NOW)
    assert w.kind == "date"
    assert "yesterday" in w.label
    assert w.end_ts - w.start_ts == 86_400_000


def test_today_from_midnight_to_now():
    w = parse_time_window("status today", now=NOW)
    assert w.kind == "date"
    assert "today" in w.label
    start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
    assert start.hour == 0 and start.minute == 0
    assert w.end_ts == int(NOW.timestamp() * 1000)


def test_this_week_monday_start():
    w = parse_time_window("this week average", now=NOW)
    assert w.kind == "date"
    assert w.label == "this week"
    start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
    assert start.weekday() == 0  # Monday


def test_iso_date():
    w = parse_time_window("on 2026-07-20 power", now=NOW)
    assert w.kind == "date"
    assert "2026-07-20" in w.label
    assert w.end_ts - w.start_ts == 86_400_000


def test_dmy_date():
    w = parse_time_window("readings on 20/07/2026", now=NOW)
    assert w.kind == "date"
    assert "2026-07-20" in w.label


def test_morning_shift_hours():
    w = parse_time_window("morning shift oil", now=AFTERNOON_NOW)
    assert w.kind == "shift"
    start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
    end = datetime.fromtimestamp(w.end_ts / 1000, tz=IST)
    assert start.hour == 6
    assert end.hour == 14


def test_afternoon_and_evening_shift():
    for msg in ("afternoon shift", "evening shift power"):
        w = parse_time_window(msg, now=NOW)
        assert w.kind == "shift"
        start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
        assert start.hour == 14


def test_night_shift_crosses_midnight():
    w = parse_time_window("night shift", now=NIGHT_NOW)
    assert w.kind == "shift"
    start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
    end = datetime.fromtimestamp(w.end_ts / 1000, tz=IST)
    assert start < end
    # night starts previous evening 22:00
    assert start.hour == 22


def test_letter_shifts_a_b_c():
    for msg, hour in (("A shift", 6), ("shift B oil", 14), ("C shift", 22)):
        w = parse_time_window(msg, now=AFTERNOON_NOW)
        assert w.kind == "shift"
        start = datetime.fromtimestamp(w.start_ts / 1000, tz=IST)
        assert start.hour == hour


def test_generic_shift_uses_current_clock():
    w = parse_time_window("current shift status", now=AFTERNOON_NOW)
    assert w.kind == "shift"
    assert "afternoon" in w.label or "b" in w.label.lower() or "14:" in w.label


def test_yesterday_morning_shift():
    w = parse_time_window("yesterday morning shift", now=NOW)
    assert w.kind == "shift"
    assert "2026-07-20" in w.label


def test_default_relative_24h():
    w = parse_time_window("something random", now=NOW)
    assert w.kind == "relative"
    assert w.end_ts - w.start_ts == 24 * 3_600_000


def test_empty_message_defaults():
    w = parse_time_window("", now=NOW)
    assert w.kind == "relative"


def test_extract_metrics_aliases():
    keys = extract_metric_keys(
        "average power and oil and rpm",
        ["power_kw", "oil_pressure", "engine_rpm", "coolant_temp"],
    )
    assert set(keys) == {"power_kw", "oil_pressure", "engine_rpm"}
    assert keys[0] == "power_kw"  # longer/earlier aliases preferred first


def test_extract_metrics_temperature_alias():
    keys = extract_metric_keys("temperature trend", ["coolant_temp", "power_kw"])
    assert keys == ["coolant_temp"]


def test_extract_metrics_fallback_defaults():
    fallback = ["power_kw", "engine_rpm", "coolant_temp", "oil_pressure", "fuel_level", "other"]
    keys = extract_metric_keys("show stats", fallback)
    assert keys == ["power_kw", "engine_rpm", "coolant_temp", "oil_pressure", "fuel_level"]


def test_extract_metrics_fallback_when_no_defaults():
    keys = extract_metric_keys("show stats", ["rssi", "snr", "uptime"])
    assert keys == ["rssi", "snr", "uptime"]


def test_extract_metrics_empty_message_and_keys():
    assert extract_metric_keys("", []) == []
