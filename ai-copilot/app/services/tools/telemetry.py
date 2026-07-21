from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.tb_client import ThingsBoardClient

DG_KEYS = [
    "dg_status", "common_alarm", "power_kw", "engine_rpm", "coolant_temp", "oil_pressure",
    "fuel_level", "battery_voltage", "frequency", "ai_status", "severity", "summary",
    "maintenance_recommendation", "health_score", "failure_risk_pct", "rul_hours",
    "predicted_coolant_1h",
]

GATEWAY_KEYS = [
    "rssi", "snr", "uptime", "connected", "status", "cpu", "memory", "disk",
]

AI_KEYS = [
    "ai_status", "severity", "summary", "maintenance_recommendation",
    "health_score", "failure_risk_pct", "rul_hours", "predicted_coolant_1h",
]

DISPLAY = {
    "dg_status": "DG Status",
    "common_alarm": "Common Alarm",
    "power_kw": "Power (kW)",
    "engine_rpm": "Engine RPM",
    "coolant_temp": "Coolant Temperature",
    "oil_pressure": "Oil Pressure",
    "fuel_level": "Fuel Level",
    "battery_voltage": "Battery Voltage",
    "frequency": "Frequency",
    "ai_status": "AI Status",
    "severity": "AI Severity",
    "summary": "AI Summary",
    "maintenance_recommendation": "Maintenance Recommendation",
    "health_score": "Health Score",
    "failure_risk_pct": "Failure Risk %",
    "rul_hours": "RUL Hours",
    "predicted_coolant_1h": "Predicted Coolant 1h",
}


def normalize_value(raw: Any) -> str:
    if raw is None or raw == "":
        return "N/A"
    try:
        num = float(raw)
        if num >= 30000:
            return "N/A"
        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(raw)


def keys_for_device(name: str | None, device_type: str | None = None) -> list[str]:
    n = (name or "").lower()
    t = (device_type or "").lower()
    if "gateway" in n or "gateway" in t:
        return GATEWAY_KEYS + AI_KEYS
    return DG_KEYS


def flatten_latest(ts: dict[str, Any]) -> tuple[dict[str, str], int | None]:
    values: dict[str, str] = {}
    latest_ts: int | None = None
    for key, points in (ts or {}).items():
        if not points:
            continue
        point = points[0]
        val = point.get("value")
        ts_val = point.get("ts")
        label = DISPLAY.get(key, key)
        values[label] = normalize_value(val)
        if isinstance(ts_val, int):
            latest_ts = max(latest_ts or 0, ts_val)
    return values, latest_ts


async def fetch_latest_snapshot(client: ThingsBoardClient, device_id: UUID, device_name: str, device_type: str | None = None) -> dict[str, Any]:
    keys = keys_for_device(device_name, device_type)
    raw = await client.latest_telemetry(device_id, keys)
    values, latest_ts = flatten_latest(raw)
    return {
        "deviceName": device_name,
        "lastTelemetryTs": latest_ts,
        "values": values,
        "raw": raw,
    }


async def fetch_active_alarms(client: ThingsBoardClient, device_id: UUID) -> list[dict[str, Any]]:
    page = await client.active_alarms(device_id)
    out = []
    for item in page.get("data") or []:
        details = item.get("details")
        if isinstance(details, dict):
            details_text = details.get("message") or details.get("text") or str(details)
        else:
            details_text = str(details) if details is not None else None
        out.append(
            {
                "severity": item.get("severity"),
                "type": item.get("type"),
                "status": item.get("status"),
                "details": details_text,
            }
        )
    return out


async def fetch_ai_scores(client: ThingsBoardClient, device_id: UUID) -> dict[str, str]:
    raw = await client.latest_telemetry(device_id, AI_KEYS)
    values, _ = flatten_latest(raw)
    return values


async def fetch_history(
    client: ThingsBoardClient,
    device_id: UUID,
    device_name: str,
    start_ts: int,
    end_ts: int,
) -> dict[str, Any]:
    keys = keys_for_device(device_name)[:8]
    raw = await client.history_telemetry(device_id, keys, start_ts, end_ts, limit=20)
    summary: dict[str, Any] = {}
    for key, points in (raw or {}).items():
        if not points:
            continue
        summary[DISPLAY.get(key, key)] = {
            "points": len(points),
            "first": normalize_value(points[-1].get("value")),
            "last": normalize_value(points[0].get("value")),
        }
    return summary
