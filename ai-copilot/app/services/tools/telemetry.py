from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from app.services.tb_client import ThingsBoardClient

DISPLAY_MAP: dict[str, str] = {
    # DG Sets (Woodward KG1500)
    "dg_status": "DG Status",
    "status": "Operational Status",
    "common_alarm": "Common Alarm",
    "power_kw": "Active Power (kW)",
    "engine_rpm": "Engine RPM",
    "coolant_temp": "Coolant Temperature (°C)",
    "oil_pressure": "Oil Pressure (bar)",
    "fuel_level": "Fuel Level (%)",
    "battery_voltage": "Battery Voltage (V)",
    "frequency": "Frequency (Hz)",
    "energy_kwh": "Total Energy (kWh)",
    "run_hours": "Running Hours",
    "power_factor": "Power Factor",
    "voltage": "Line Voltage (V)",
    "current": "Current (A)",
    "ai_status": "AI Diagnostics",
    "severity": "AI Severity",
    "summary": "AI Summary",
    "health_score": "Health Score",
    "failure_risk_pct": "Failure Risk %",
    "rul_hours": "Estimated RUL (Hours)",
    "predicted_coolant_1h": "Predicted Coolant in 1h",
    "maintenance_recommendation": "Maintenance Action",

    # RO Plant System
    "tds_ppm": "TDS (ppm)",
    "tds": "TDS (ppm)",
    "water_flow": "Water Flow Rate (m³/h)",
    "pressure": "Operating Pressure (bar)",
    "ph": "Water pH",
    "salinity_ppm": "Salinity (ppm)",
    "ec_us_cm": "Conductivity (µS/cm)",
    "temperature_c": "Water Temperature (°C)",
    "flow_total": "Total Flow",
    "tds_online": "TDS Sensor Status",
    "flow_online": "Flow Sensor Status",

    # Fire Suppression (Main & UPS Room 2)
    "relay_online": "Relay Gateway Status",
    "low_pressure": "Low Pressure Line",
    "high_pressure": "High Pressure Line",
    "low_pressure_alarm": "Low Pressure Alarm",
    "high_pressure_alarm": "High Pressure Alarm",
    "di_raw": "Digital Inputs Raw",
    "di1": "Abort Switch (DI1)",
    "di2": "Discharge Pressure Switch (DI2)",
    "di3": "Manual Release Switch (DI3)",
}

# Auto-add cylinder pressure keys
for i in range(1, 11):
    DISPLAY_MAP[f"cylinder_pressure_{i}"] = f"Cylinder {i} Pressure (bar)"
    DISPLAY_MAP[f"fire_suppression_{i}_pressure"] = f"Gas Cylinder {i} Status"

# Auto-add LT Panels keys
PANELS = [
    ("EVM_Charger", "EVM Charger"),
    ("Electrical_room_1", "Electrical Room 1"),
    ("UPS_Room_1", "UPS Room 1"),
    ("Transformer_1", "Transformer 1"),
    ("Transformer_2", "Transformer 2"),
    ("Transformer_3", "Transformer 3"),
    ("UPS_Panel_2", "UPS Panel 2"),
    ("Fire_fighting_wall", "Fire Fighting Wall"),
]
for pfx, label in PANELS:
    DISPLAY_MAP[f"{pfx}_power"] = f"{label} Power (kW)"
    DISPLAY_MAP[f"{pfx}_voltage"] = f"{label} Voltage (V)"
    DISPLAY_MAP[f"{pfx}_current"] = f"{label} Current (A)"
    DISPLAY_MAP[f"{pfx}_frequency"] = f"{label} Frequency (Hz)"
DISPLAY = DISPLAY_MAP

DG_KEYS = [
    "power_kw", "engine_rpm", "coolant_temp", "oil_pressure", "fuel_level",
    "battery_voltage", "frequency", "energy_kwh", "run_hours", "common_alarm", "status",
]

LT_KEYS = [f"{pfx}_{m}" for pfx, _ in PANELS for m in ("power", "voltage", "current", "frequency")]

RO_KEYS = ["status", "tds_ppm", "water_flow", "pressure", "ph", "salinity_ppm", "temperature_c", "ec_us_cm"]

FIRE_KEYS = ["relay_online", "low_pressure", "high_pressure"] + [f"cylinder_pressure_{i}" for i in range(1, 10)] + [f"fire_suppression_{i}_pressure" for i in range(1, 11)]


def keys_for_device(name: str | None = None, device_type: str | None = None) -> list[str]:
    n = (name or "").lower()
    t = (device_type or "").lower()
    if "ro" in n or "ro" in t:
        return RO_KEYS
    if "lt" in n or "panel" in n or "gateway" in n or "lt" in t:
        return LT_KEYS
    if "fire" in n or "suppression" in n or "fire" in t:
        return FIRE_KEYS
    return DG_KEYS


def normalize_value(key_or_raw: Any, raw_val: Any = None) -> str:
    if raw_val is not None:
        raw = raw_val
        key = str(key_or_raw).lower()
    else:
        raw = key_or_raw
        key = ""

    if raw is None or raw == "":
        return "N/A"
    if isinstance(raw, bool):
        return "NORMAL / OK" if raw is True else "ALERT / OFF"

    s = str(raw).strip()
    if s.lower() in ("error", "err", "32767", "65535", "32767.0", "65535.0"):
        if any(k in key for k in ("rpm", "speed", "oil", "coolant", "temp")):
            return "Engine Standby (Stopped)"
        return "Standby / Inactive"

    try:
        num = float(raw)
        if num in (32767.0, 65535.0) or num >= 30000:
            if any(k in key for k in ("rpm", "speed", "oil", "coolant", "temp")):
                return "Engine Standby (Stopped)"
            return "Standby / Inactive"

        # Specific key formatting
        if key in ("status", "dg_status"):
            return "STANDBY (STOPPED)" if num == 0 else "RUNNING"
        if "fuel" in key:
            return f"{num:.1f}%" if not num.is_integer() else f"{int(num)}%"
        if "battery" in key:
            return f"{num:.1f} V"
        if "frequency" in key or "freq" in key:
            return f"{num:.1f} Hz"
        if "power_kw" in key or key.endswith("_power"):
            return f"{num:.1f} kW"
        if "pressure" in key and "cylinder" in key:
            return "NORMAL (0)" if num == 0 else f"{num:.1f} bar"
        if "water_flow" in key:
            return f"{num:.1f} m³/h"
        if "tds" in key:
            return f"{int(num)} ppm"

        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")
    except Exception:
        if s.lower() in ("true", "online", "normal"):
            return "NORMAL / ONLINE"
        if s.lower() in ("false", "offline"):
            return "OFFLINE"
        return s


GATEWAY_SYSTEM_KEYS = {"rssi", "snr", "uptime", "connected", "cpu", "memory", "disk"}


def clean_alarm_text(raw_details: Any) -> str | None:
    if not raw_details:
        return None
    if isinstance(raw_details, dict):
        text = raw_details.get("data") or raw_details.get("message") or raw_details.get("msg") or raw_details.get("text") or str(raw_details)
    else:
        text = str(raw_details)

    # Strip stringified json dictionary wrapper if present
    text = re.sub(r"^\{['\"]data['\"]:\s*['\"]", "", text)
    text = re.sub(r"['\"]\}\s*$", "", text)
    # Strip unresolved template variables like ${Transformer_1_current}
    text = re.sub(r"\$\{[^}]+\}\s*", "", text)
    # Clean redundant spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def flatten_latest(ts: dict[str, Any]) -> tuple[dict[str, str], int | None]:
    values: dict[str, str] = {}
    latest_ts: int | None = None
    for key, points in (ts or {}).items():
        if not points:
            continue
        lowered_key = key.lower()
        if lowered_key in GATEWAY_SYSTEM_KEYS:
            continue

        point = points[0]
        val = point.get("value")
        ts_val = point.get("ts")
        
        normalized = normalize_value(key, val)
        if normalized in ("N/A", "", "None"):
            continue

        label = DISPLAY_MAP.get(key, key.replace("_", " ").title())
        values[label] = normalized
        if isinstance(ts_val, int):
            latest_ts = max(latest_ts or 0, ts_val)
    return values, latest_ts


async def fetch_latest_snapshot(
    client: ThingsBoardClient,
    device_id: UUID,
    device_name: str,
    device_type: str | None = None,
) -> dict[str, Any]:
    # Pass None to fetch ALL latest telemetry keys dynamically
    raw = await client.latest_telemetry(device_id, keys=None)
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
        details_text = clean_alarm_text(details)
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
    raw = await client.latest_telemetry(device_id, ["health_score", "failure_risk_pct", "rul_hours", "ai_status"])
    values, _ = flatten_latest(raw)
    return values


async def fetch_fleet_overview(client: ThingsBoardClient, devices: list[Any]) -> list[dict[str, Any]]:
    """Fetch live snapshots and active alarms for all devices concurrently."""
    async def get_device_summary(d):
        d_id = d.id if hasattr(d, "id") else UUID(d["id"]["id"])
        d_name = d.name if hasattr(d, "name") else d["name"]
        d_type = d.type if hasattr(d, "type") else d.get("type", "")

        try:
            snap = await fetch_latest_snapshot(client, d_id, d_name, d_type)
            alarms = await fetch_active_alarms(client, d_id)
            return {
                "id": str(d_id),
                "name": d_name,
                "type": d_type,
                "values": snap.get("values", {}),
                "alarms": alarms,
            }
        except Exception as e:
            return {
                "id": str(d_id),
                "name": d_name,
                "type": d_type,
                "values": {},
                "alarms": [],
                "error": str(e),
            }

    tasks = [get_device_summary(d) for d in devices]
    return await asyncio.gather(*tasks)
