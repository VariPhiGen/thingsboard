"""Collects per-device telemetry, 24h statistics, graph series and alarms from ThingsBoard."""
import logging
from collections import Counter
from datetime import datetime

from .config import REPORT_TZ
from .metrics import bucket_series, integrate_energy_kwh, report_window, sample_stats, valid_samples

log = logging.getLogger(__name__)

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
    "dg": {"power_kw", "fuel_level", "battery_voltage", "coolant_temp", "oil_pressure", "engine_rpm", "energy_kwh"},
    "lt": {f"{prefix}_{m}" for _, prefix in LT_PANELS for m in ("power", "voltage", "current", "frequency")},
    "fire": {"relay_online"} | {f"cylinder_pressure_{i}" for i in range(1, 10)},
    "ro": {"tds", "water_flow", "pressure", "ph"},
}


def classify(device, profiles):
    """Report category of a device from its ThingsBoard device profile (type), or None."""
    for category, types in profiles.items():
        if device.get("type") in types:
            return category
    return None


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts / 1000, REPORT_TZ).strftime("%Y-%m-%d %H:%M:%S") if ts else "No activity"


def collect_device(client, device, category, start_ts, end_ts, historical):
    dev_id = device["id"]["id"]
    keys = client.timeseries_keys(dev_id)
    latest = client.latest(dev_id, keys, end_ts if historical else None)

    history = client.history(dev_id, sorted(k for k in keys if k in HISTORY_KEYS.get(category, ())), start_ts, end_ts)
    series, agg = {}, {}
    energy_kwh = energy_coverage = None
    for key, points in history.items():
        samples = valid_samples(points)
        series[key] = bucket_series(samples, start_ts, end_ts)
        for stat, value in sample_stats(samples).items():
            agg[f"{key}_24h_{stat}"] = value
        if key == "power_kw":
            energy_kwh, energy_coverage = integrate_energy_kwh(samples, start_ts, end_ts)

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
