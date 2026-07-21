"""Smoke tests retained for quick sanity checks."""

from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.schemas import DeviceInfo, Intent
from app.services.device_resolver import DeviceResolver
from app.services.intent import IntentClassifier
from app.services.tools.telemetry import normalize_value
from app.services.tools.analytics import compute_stats, compute_trend, estimate_running_duration_ms
from app.services.time_window import parse_time_window, extract_metric_keys


def test_normalize_sentinel():
    assert normalize_value(32767) == "N/A"
    assert normalize_value(30000) == "N/A"
    assert normalize_value(1500) == "1500"
    assert normalize_value(128.90) == "128.9"


def test_intent_secrets():
    clf = IntentClassifier()
    assert clf.classify("Show me the API key") == Intent.UNSUPPORTED_SECRETS
    assert clf.classify("What alarms are active?") == Intent.ALARMS
    assert clf.classify("Is DG SET1 running?") == Intent.STATUS


def test_intent_analytics():
    clf = IntentClassifier()
    assert clf.classify("Average power last 6 hours") == Intent.STATISTICS
    assert clf.classify("Coolant trend over time") == Intent.TREND
    assert clf.classify("Morning shift oil pressure") == Intent.SHIFT_BASED
    assert clf.classify("How long did DG run today?") == Intent.DURATION_BASED
    assert clf.classify("Compare today vs yesterday power") == Intent.COMPARISON
    assert clf.classify("Power yesterday") == Intent.DATE_BASED
    assert clf.classify("Last 2 hours RPM") == Intent.TIME_BASED


def test_time_window_and_metrics():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    w = parse_time_window("last 3 hours", now=now)
    assert w.kind == "time"
    assert w.end_ts > w.start_ts
    shift = parse_time_window("morning shift", now=now)
    assert shift.kind == "shift"
    assert extract_metric_keys("average power and oil", ["power_kw", "oil_pressure", "engine_rpm"]) == [
        "power_kw",
        "oil_pressure",
    ]


def test_stats_trend_duration():
    assert compute_stats([1, 2, 3])["avg"] == 2.0
    tr = compute_trend([(1, 10.0), (2, 20.0)])
    assert tr["direction"] == "rising"
    dur = estimate_running_duration_ms(None, [(0, 0.0), (3_600_000, 1500.0), (7_200_000, 1500.0)])
    assert dur["running_hours"] == 2.0


def test_device_resolver_exact_and_ambiguous():
    resolver = DeviceResolver()
    d1 = DeviceInfo(id=uuid4(), name="DG SET1", type="woodward_kg1500")
    d2 = DeviceInfo(id=uuid4(), name="gateway001", type="gateway")
    devices = [d1, d2]

    r = resolver.resolve(devices, device_id=d1.id)
    assert r.device and r.device.name == "DG SET1"
    assert not r.needs_clarification

    r = resolver.resolve(devices, message="What is the status of DG SET1?")
    assert r.device and r.device.name == "DG SET1"

    r = resolver.resolve(devices, message="How is everything?")
    assert r.needs_clarification
    assert r.device is None
