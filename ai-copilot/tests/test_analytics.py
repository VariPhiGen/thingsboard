"""Analytics helpers — stats, trend, duration, analyze/compare edge cases."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.time_window import TimeWindow
from app.services.tools.analytics import (
    _series_values,
    _to_float,
    analyze_window,
    compare_devices,
    compare_periods,
    compute_stats,
    compute_trend,
    estimate_running_duration_ms,
    fetch_window_series,
)


def test_to_float_valid_and_sentinel():
    assert _to_float("12.5") == 12.5
    assert _to_float(0) == 0.0
    assert _to_float(32767) is None
    assert _to_float(30000) is None
    assert _to_float(None) is None
    assert _to_float("") is None
    assert _to_float("abc") is None


def test_series_values_sorts_and_skips_invalid():
    points = [
        {"ts": 3000, "value": "30"},
        {"ts": 1000, "value": "10"},
        {"ts": 2000, "value": "32767"},
        {"ts": "bad", "value": "5"},
        {"value": "9"},
    ]
    series = _series_values(points)
    assert series == [(1000, 10.0), (3000, 30.0)]


def test_compute_stats_empty():
    assert compute_stats([]) == {"count": 0}


def test_compute_stats_single_and_many():
    assert compute_stats([5.0])["avg"] == 5.0
    st = compute_stats([1, 2, 3, 4])
    assert st["min"] == 1
    assert st["max"] == 4
    assert st["avg"] == 2.5
    assert st["first"] == 1
    assert st["last"] == 4
    assert st["count"] == 4


def test_compute_trend_insufficient():
    assert compute_trend([])["direction"] == "insufficient_data"
    assert compute_trend([(1, 1.0)])["direction"] == "insufficient_data"


def test_compute_trend_rising_falling_stable():
    assert compute_trend([(1, 10.0), (2, 20.0)])["direction"] == "rising"
    assert compute_trend([(1, 20.0), (2, 10.0)])["direction"] == "falling"
    assert compute_trend([(1, 10.0), (2, 10.0)])["direction"] == "stable"


def test_compute_trend_zero_baseline_pct():
    tr = compute_trend([(1, 0.0), (2, 5.0)])
    assert tr["direction"] == "rising"
    assert tr["change_pct"] is None


def test_duration_insufficient():
    out = estimate_running_duration_ms(None, None)
    assert out["running_hours"] == 0.0
    assert out["method"] == "insufficient_data"


def test_duration_from_rpm():
    rpm = [(0, 0.0), (3_600_000, 1500.0), (7_200_000, 1500.0), (10_800_000, 50.0)]
    out = estimate_running_duration_ms(None, rpm)
    assert out["method"] == "engine_rpm"
    # intervals where current sample > 100: 1h->2h (1h) and 2h->3h (1h) = 2h
    assert out["running_hours"] == 2.0


def test_duration_from_status_when_no_rpm():
    status = [(0, 0.0), (3_600_000, 1.0), (7_200_000, 1.0)]
    out = estimate_running_duration_ms(status, None)
    assert out["method"] == "dg_status"
    assert out["running_hours"] == 2.0


def test_duration_prefers_rpm_over_status():
    status = [(0, 1.0), (3_600_000, 1.0)]
    rpm = [(0, 0.0), (3_600_000, 0.0)]
    out = estimate_running_duration_ms(status, rpm)
    assert out["method"] == "engine_rpm"
    assert out["running_hours"] == 0.0


def test_analyze_window_modes():
    window = TimeWindow(0, 3600000, "last 1 hour", "time")
    payload = {
        "keys": ["power_kw", "engine_rpm"],
        "raw": {
            "power_kw": [{"ts": 0, "value": "10"}, {"ts": 1000, "value": "20"}],
            "engine_rpm": [{"ts": 0, "value": "1500"}, {"ts": 1000, "value": "1500"}],
        },
    }
    for mode in ("statistics", "trend", "duration", "time", "date", "shift", "general"):
        text = analyze_window("DG SET1", window, payload, mode)
        assert "DG SET1" in text
        assert "Analysis window" in text


def test_analyze_window_no_samples():
    window = TimeWindow(0, 1000, "empty", "time")
    text = analyze_window("DG SET1", window, {"keys": ["power_kw"], "raw": {}}, "statistics")
    assert "no valid samples" in text


@pytest.mark.asyncio
async def test_fetch_window_series_builds_keys(monkeypatch):
    class FakeClient:
        async def history_telemetry(self, *args, **kwargs):
            return {"power_kw": [{"ts": 1, "value": "5"}]}

    window = TimeWindow(0, 3_600_000, "last 1 hour", "time")
    out = await fetch_window_series(
        FakeClient(), uuid4(), "DG SET1", window, "average power", "woodward_kg1500"
    )
    assert "power_kw" in out["keys"]
    assert "engine_rpm" in out["keys"] or "dg_status" in out["keys"]
    assert out["raw"]["power_kw"][0]["value"] == "5"
    assert out["interval_ms"] >= 60_000


@pytest.mark.asyncio
async def test_compare_periods_and_devices():
    class FakeClient:
        async def history_telemetry(self, device_id, keys, *args, **kwargs):
            return {
                "power_kw": [
                    {"ts": 1, "value": "10"},
                    {"ts": 2, "value": "20"},
                ]
            }

    wa = TimeWindow(0, 1000, "A", "date")
    wb = TimeWindow(1000, 2000, "B", "date")
    device_id = uuid4()
    text = await compare_periods(
        FakeClient(), device_id, "DG SET1", "compare power", wa, wb, "woodward_kg1500"
    )
    assert "Period A" in text and "Period B" in text
    assert "Power" in text or "power" in text.lower()

    text2 = await compare_devices(
        FakeClient(),
        [(device_id, "DG SET1", "woodward_kg1500"), (uuid4(), "gateway001", "gateway")],
        "compare power",
        wa,
    )
    assert "Device comparison" in text2
    assert "DG SET1" in text2
