"""Collects per-device telemetry, 24h statistics, graph series and alarms from ThingsBoard."""
import json
import logging
import re
from collections import Counter
from datetime import datetime

from .config import REPORT_TZ
from .metrics import (
    RUNNING_KW, bucket_series, count_runs, integrate_energy_kwh, report_window, resolve_report_date, sample_stats,
    valid_samples,
)

log = logging.getLogger(__name__)

# An alarm cleared this soon after it started is a status flicker, not an equipment event
TRANSIENT_ALARM_MS = 2 * 60 * 1000
# Alarm details quoting a sensor-offline code (Modbus 0x7FFF / 0xFFFF) were raised on a missing reading
_SENSOR_OFFLINE_RE = re.compile(r"(?<![\d.])(32767|65535)(\.0+)?(?![\d.])")

EXCLUDED_DUPLICATE = "duplicate"
EXCLUDED_SENSOR = "sensor offline reading"
EXCLUDED_TRANSIENT = "cleared within 2 min"
EXCLUDED_ENGINE_STOPPED = "raised while engine stopped"

# Alarms that only mean something while the engine runs (oil pressure is 0 on a stopped engine)
ENGINE_RUNNING_ALARMS = {"Low Oil Pressure"}
# Alarm types that record a DG starting or stopping, not a fault: reported as runs, not alarms
OPERATIONAL_ALARM_TYPES = {"DG Offline"}
# How far back the last engine reading may be when judging an alarm raised while stopped
ENGINE_STATE_LOOKBACK_MS = 5 * 60 * 1000

LT_PANELS = [
    ("EVM Charger", "EVM_Charger"),
    ("Electrical Room 1", "Electrical_room_1"),
    ("UPS Room 1", "UPS_Room_1"),
    ("Transformer 1", "Transformer_1"),
    ("Transformer 2", "Transformer_2"),
    ("Transformer 3", "Transformer_3"),
    ("UPS Panel 2", "UPS_Panel_2"),
    ("Fire Fighting Wall", "Fire_fighting_wall"),
]

# Keys whose raw history is fetched for graphs and 24h statistics, per report category
HISTORY_KEYS = {
    "dg": {"power_kw", "fuel_level", "battery_voltage", "coolant_temp", "oil_pressure", "engine_rpm", "energy_kwh",
           "run_hours"},
    "lt": {f"{prefix}_{m}" for _, prefix in LT_PANELS for m in ("power", "voltage", "current", "frequency")},
    "fire": {"relay_online", "relay_1_online", "relay_2_online", "low_pressure", "high_pressure", "di1", "di2", "di3"} | {f"cylinder_pressure_{i}" for i in range(1, 10)} | {f"fire_suppression_{i}_pressure" for i in range(1, 11)},
    "ro": {"tds", "tds_ppm", "water_flow", "pressure", "ph", "salinity_ppm", "temperature_c", "ec_us_cm"},
}


def classify(device, profiles):
    """Report category of a device from its ThingsBoard device profile (type), or None."""
    for category, types in profiles.items():
        if device.get("type") in types:
            return category
    return None


def engine_stopped_at(ts, rpm_samples, power_samples):
    """True when the last valid reading before ts shows a stopped engine (RPM <= 100 and power <= 5 kW),
    False when it shows a running one, None when there is no reading within ENGINE_STATE_LOOKBACK_MS."""
    def last(samples):
        prior = [(t, v) for t, v in samples if ts - ENGINE_STATE_LOOKBACK_MS <= t <= ts and v not in (32767.0, 65535.0)]
        return prior[-1][1] if prior else None
    rpm, power = last(rpm_samples), last(power_samples)
    if rpm is None and power is None:
        return None
    return not ((rpm is not None and rpm > 100) or (power is not None and power > RUNNING_KW))


def screen_alarms(alarms, engine_stopped=None):
    """(equipment alarms, Counter of excluded alarms by reason).

    Excluded, in this order: a second alarm of the same type and start time, an alarm raised on a
    sensor-offline code, a non-CRITICAL alarm cleared within TRANSIENT_ALARM_MS of its start (a short
    CRITICAL alarm can be a real event, so it is always counted), and an engine-running alarm raised
    while engine_stopped(start_ts) says the engine was stopped."""
    kept, excluded, seen = [], Counter(), set()
    for alarm in alarms:
        start = alarm.get("startTs") or alarm.get("createdTime") or 0
        key = (alarm.get("type"), start)
        clear_ts = alarm.get("clearTs") or 0
        if key in seen:
            excluded[EXCLUDED_DUPLICATE] += 1
        elif _SENSOR_OFFLINE_RE.search(json.dumps(alarm.get("details") or "")):
            excluded[EXCLUDED_SENSOR] += 1
        elif (clear_ts and alarm.get("severity") != "CRITICAL"
              and 0 <= clear_ts - start < TRANSIENT_ALARM_MS):
            excluded[EXCLUDED_TRANSIENT] += 1
        elif alarm.get("type") in ENGINE_RUNNING_ALARMS and engine_stopped and engine_stopped(start) is True:
            excluded[EXCLUDED_ENGINE_STOPPED] += 1
        else:
            kept.append(alarm)
        seen.add(key)
    return kept, excluded


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts / 1000, REPORT_TZ).strftime("%Y-%m-%d %H:%M:%S") if ts else "No activity"


def collect_device(client, device, category, start_ts, end_ts, historical):
    dev_id = device["id"]["id"]
    keys = client.timeseries_keys(dev_id)
    latest = client.latest(dev_id, keys, end_ts if historical else None)

    history = client.history(dev_id, sorted(k for k in keys if k in HISTORY_KEYS.get(category, ())), start_ts, end_ts)
    series, agg, samples_by_key = {}, {}, {}
    energy_kwh = energy_coverage = runs = None
    for key, points in history.items():
        samples = samples_by_key[key] = valid_samples(points)
        series[key] = bucket_series(samples, start_ts, end_ts)
        for stat, value in sample_stats(samples).items():
            agg[f"{key}_24h_{stat}"] = value
        if key == "power_kw":
            energy_kwh, energy_coverage = integrate_energy_kwh(samples, start_ts, end_ts)
    if "power_kw" in samples_by_key or "engine_rpm" in samples_by_key:
        runs = count_runs(samples_by_key.get("power_kw", []), start_ts, end_ts, samples_by_key.get("engine_rpm", []))

    if historical:
        # The current 'active' attribute says nothing about a past day: online = sent data that day
        in_window = [ts for ts, _ in latest.values() if start_ts <= ts < end_ts]
        is_active = bool(in_window)
        last_activity = _fmt_ts(max((ts for ts, _ in latest.values()), default=0))
        alarms = client.alarms(dev_id, start_ts=start_ts, end_ts=end_ts)
    else:
        attrs = client.attributes(dev_id)
        is_active = bool(attrs.get("active", False))
        last_activity = _fmt_ts(attrs.get("lastActivityTime", 0))
        alarms = client.alarms(dev_id, active_only=True)
    # A device's alarm list also holds alarms propagated from related devices (DG Set 2/3 alarms show up
    # under DG SET1); count only the alarms this device raised so nothing is counted twice
    alarms = [a for a in alarms if a.get("originator", {}).get("id") == dev_id]
    engine_stopped = None
    if "engine_rpm" in samples_by_key or "power_kw" in samples_by_key:
        def engine_stopped(ts):
            return engine_stopped_at(ts, samples_by_key.get("engine_rpm", []), samples_by_key.get("power_kw", []))
    alarms, alarms_excluded = screen_alarms(alarms, engine_stopped)
    operational = Counter(a.get("type") for a in alarms if a.get("type") in OPERATIONAL_ALARM_TYPES)
    alarms = [a for a in alarms if a.get("type") not in OPERATIONAL_ALARM_TYPES]

    return {
        "id": dev_id,
        "name": device["name"],
        "type": device.get("type", "DEFAULT"),
        "category": category,
        "is_active": is_active,
        "last_activity": last_activity,
        "telemetry": {k: v for k, (_, v) in latest.items()},
        "telemetry_ts": {k: ts for k, (ts, _) in latest.items()},
        "agg_24h": agg,
        "energy_24h_kwh": energy_kwh,
        "energy_coverage": energy_coverage,
        "alarms_count": len(alarms),
        "alarm_types": dict(Counter(a.get("type", "Unknown") for a in alarms)),
        "active_alarms": [a.get("type") for a in alarms],
        "alarms_excluded": dict(alarms_excluded),
        "operational_events": dict(operational),
        "runs_24h": runs,
        "series_start_ts": start_ts,
        "series_end_ts": end_ts,
        "historical": historical,
        "series_24h": series,
    }


class DeviceSummary(list):
    """List of per-device dicts that also carries the report period."""

    def __init__(self, devices=(), start_ts=0, end_ts=0, historical=False):
        super().__init__(devices)
        self.start_ts, self.end_ts, self.historical = start_ts, end_ts, historical


def period_of(summary):
    """(start_ts, end_ts, historical) of a summary; plain lists fall back to their first device."""
    if isinstance(summary, DeviceSummary):
        return summary.start_ts, summary.end_ts, summary.historical
    if summary:
        first = summary[0]
        return first["series_start_ts"], first.get("series_end_ts", first["series_start_ts"]), first.get("historical", False)
    start_ts, end_ts = report_window()
    return start_ts, end_ts, False


def collect_summary(client, profiles, report_date=None):
    """Summary dicts for every device that belongs to one of the reports."""
    report_date = resolve_report_date(report_date)
    start_ts, end_ts = report_window(report_date)
    historical = bool(report_date)
    summary = DeviceSummary(start_ts=start_ts, end_ts=end_ts, historical=historical)
    for device in client.devices():
        category = classify(device, profiles)
        if category is None:
            log.debug("Skipping device %s (profile %s not in any report)", device["name"], device.get("type"))
            continue
        summary.append(collect_device(client, device, category, start_ts, end_ts, historical))
    found = Counter(d["category"] for d in summary)
    for category in profiles:
        if not found[category]:
            log.warning("No device with profile %s found for the %s report", profiles[category], category)
    return summary
