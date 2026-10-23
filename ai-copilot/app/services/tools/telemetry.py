from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

from app.services.tb_client import ThingsBoardClient

DISPLAY_MAP: dict[str, str] = {
    # DG Sets - Primary Status & Operations
    "dg_status": "DG Operational Status",
    "status": "Operational Status",
    "engine_state": "Engine Operating State",
    "op_mode": "Operating Mode",
    "remote_start": "Remote Start Control",
    "emergency_stop": "Emergency Stop Switch",
    "comm_ok": "Modbus Communications Status",
    "common_alarm": "Common Alarm Status",
    "breaker_state": "Breaker Operating State",
    "gcb_closed": "Generator Circuit Breaker (GCB)",
    "mcb_closed": "Mains Circuit Breaker (MCB)",
    "mains_ok": "Mains Grid Power Health",

    # DG Sets - Electrical Outputs
    "power_kw": "Active Power (kW)",
    "voltage": "Line Voltage (V)",
    "voltage_delta": "Voltage Deviation (V)",
    "current": "Current (A)",
    "frequency": "Frequency (Hz)",
    "power_factor": "Power Factor (cos φ)",
    "sync_phase_deg": "Sync Phase Angle (°)",
    "energy_kwh": "Total Energy (kWh)",
    "gen_kwh_export": "Export Energy (kWh)",
    "gen_kva_total": "Total Apparent Power (kVA)",
    "gen_kvar_total": "Total Reactive Power (kVAR)",
    "gen_kvarh": "Total Reactive Energy (kVARh)",
    "bus_v": "Bus Voltage (V)",
    "bus_freq": "Bus Frequency (Hz)",

    # DG Sets - Phase Voltages & Currents
    "gen_v_l12": "Gen Line Voltage L1-L2 (V)",
    "gen_v_l23": "Gen Line Voltage L2-L3 (V)",
    "gen_v_l31": "Gen Line Voltage L3-L1 (V)",
    "gen_v_l1n": "Gen Phase Voltage L1-N (V)",
    "gen_v_l2n": "Gen Phase Voltage L2-N (V)",
    "gen_v_l3n": "Gen Phase Voltage L3-N (V)",
    "gen_i_l1": "Gen Phase Current L1 (A)",
    "gen_i_l2": "Gen Phase Current L2 (A)",
    "gen_i_l3": "Gen Phase Current L3 (A)",
    "gen_i_neutral": "Gen Neutral Current (A)",
    "gen_kw_l1": "Gen Active Power L1 (kW)",
    "gen_kw_l2": "Gen Active Power L2 (kW)",
    "gen_kw_l3": "Gen Active Power L3 (kW)",
    "gen_i_unbalance_pct": "Current Unbalance (%)",
    "gen_v_unbalance_pct": "Voltage Unbalance (%)",
    "gen_phase_seq": "Generator Phase Sequence",

    # DG Sets - Mains Grid 3-Phase
    "mains_v_l12": "Mains Voltage L1-L2 (V)",
    "mains_v_l23": "Mains Voltage L2-L3 (V)",
    "mains_v_l31": "Mains Voltage L3-L1 (V)",
    "mains_v_l1n": "Mains Phase Voltage L1-N (V)",
    "mains_v_l2n": "Mains Phase Voltage L2-N (V)",
    "mains_v_l3n": "Mains Phase Voltage L3-N (V)",
    "mains_kw": "Mains Active Power (kW)",
    "mains_freq": "Mains Grid Frequency (Hz)",
    "mains_phase_seq": "Mains Phase Sequence",

    # DG Sets - Engine Mechanical & Sensors
    "engine_rpm": "Engine RPM",
    "engine_speed_target": "Target Engine Speed (RPM)",
    "turbo_speed": "Turbocharger Speed (RPM)",
    "engine_load_pct": "Engine Load (%)",
    "gen_load_pct": "Generator Load (%)",
    "engine_torque_pct": "Engine Torque (%)",
    "battery_voltage": "Battery Voltage (V)",
    "starter_battery_v": "Starter Battery Voltage (V)",
    "battery_i": "Battery Current (A)",
    "battery_temp": "Battery Temperature (°C)",
    "charge_alt_v": "Charge Alternator Voltage (V)",
    "charge_alt_i": "Charge Alternator Current (A)",
    "coolant_temp": "Coolant Temperature (°C)",
    "coolant_pressure": "Coolant Pressure (kPa)",
    "coolant_level_pct": "Coolant Level (%)",
    "oil_pressure": "Oil Pressure (bar)",
    "oil_temp": "Oil Temperature (°C)",
    "oil_level": "Oil Level Status",
    "oil_level_pct": "Oil Level (%)",
    "fuel_level": "Fuel Tank Level (%)",
    "fuel_level_l": "Fuel Tank Volume (L)",
    "fuel_consumed_l": "Cumulative Fuel Consumed (L)",
    "fuel_rate_lph": "Fuel Consumption Rate (L/h)",
    "fuel_pressure": "Fuel Pressure (kPa)",
    "fuel_temp": "Fuel Temperature (°C)",
    "boost_pressure": "Turbo Boost Pressure (kPa)",
    "intake_manifold_pressure": "Intake Manifold Pressure (kPa)",
    "intake_manifold_temp": "Intake Manifold Temp (°C)",
    "exhaust_temp_l": "Exhaust Temp Left Bank (°C)",
    "exhaust_temp_r": "Exhaust Temp Right Bank (°C)",
    "engine_ecu_temp": "ECU Module Temperature (°C)",
    "controller_temp": "Controller Enclosure Temp (°C)",
    "ambient_temp": "Ambient Temperature (°C)",
    "barometric_kpa": "Barometric Pressure (kPa)",
    "def_level_pct": "DEF Level (%)",
    "dpf_soot_pct": "DPF Soot Level (%)",

    # DG Sets - Maintenance & AI Diagnostics
    "run_hours": "Cumulative Run Hours (Hours)",
    "engine_hours_total": "Engine Lifetime Hours (Hours)",
    "engine_starts": "Engine Starts Count",
    "start_attempts": "Start Attempts Count",
    "shutdown_count": "Emergency Shutdown Count",
    "warning_count": "Active Warnings Count",
    "maintenance_due_h": "Maintenance Due In (Hours)",
    "ai_status": "AI Diagnostic Health Status",
    "severity": "AI Diagnostic Severity",
    "summary": "AI Health Summary",
    "health_score": "Equipment Health Score (%)",
    "failure_risk_pct": "Predicted Failure Risk (%)",
    "rul_hours": "Remaining Useful Life (Hours)",
    "predicted_coolant_1h": "Predicted Coolant Temp in 1h (°C)",
    "maintenance_recommendation": "Prescriptive Maintenance Action",

    # RO Plant System (Water Purification)
    "tds_ppm": "TDS (ppm)",
    "tds": "TDS (ppm)",
    "salinity_ppm": "Salinity (ppm)",
    "ec_us_cm": "Electrical Conductivity (µS/cm)",
    "ph": "Water pH",
    "water_flow": "Permeate Flow Rate (m³/h)",
    "flow_total": "Cumulative Water Volume (m³)",
    "pressure": "RO System Pressure (bar)",
    "temperature_c": "Water Temperature (°C)",
    "tds_online": "TDS Sensor Status",
    "flow_online": "Flow Sensor Status",

    # Fire Suppression Systems
    "relay_online": "Relay Gateway Controller Status",
    "relay_1_online": "Relay Module 1 Status",
    "relay_2_online": "Relay Module 2 Status",
    "low_pressure": "Low Pressure Header Line",
    "high_pressure": "High Pressure Discharge Line",
    "low_pressure_alarm": "Low Pressure Alert",
    "high_pressure_alarm": "High Pressure Alert",
    "di1": "Abort Switch (DI1)",
    "di2": "Discharge Pressure Switch (DI2)",
    "di3": "Manual Release Station (DI3)",
}

# Auto-add cylinder pressure keys (1 to 12)
for i in range(1, 13):
    DISPLAY_MAP[f"cylinder_pressure_{i}"] = f"Gas Cylinder {i} Status"
    DISPLAY_MAP[f"fire_suppression_{i}_pressure"] = f"Gas Cylinder {i} Status"
    DISPLAY_MAP[f"fire_suppression_{i}_high_pressure"] = f"Cylinder {i} High Pressure"
    DISPLAY_MAP[f"fire_suppression_{i}_low_pressure"] = f"Cylinder {i} Low Pressure"

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
    DISPLAY_MAP[f"{pfx}_power"] = f"{label} Active Power (kW)"
    DISPLAY_MAP[f"{pfx}_voltage"] = f"{label} Voltage (V)"
    DISPLAY_MAP[f"{pfx}_current"] = f"{label} Current (A)"
    DISPLAY_MAP[f"{pfx}_frequency"] = f"{label} Frequency (Hz)"

DISPLAY = DISPLAY_MAP

DG_KEYS = [
    "status", "dg_status", "power_kw", "battery_voltage", "fuel_level", "frequency",
    "coolant_temp", "oil_pressure", "oil_temp", "engine_rpm", "energy_kwh",
    "run_hours", "common_alarm", "voltage", "current", "starter_battery_v",
    "gen_v_l12", "gen_v_l23", "gen_v_l31", "gen_v_l1n", "gen_v_l2n", "gen_v_l3n",
    "gen_i_l1", "gen_i_l2", "gen_i_l3", "gen_i_neutral",
    "gen_kw_l1", "gen_kw_l2", "gen_kw_l3",
    "mains_v_l12", "mains_kw", "mains_freq",
    "gen_kva_total", "gen_kvar_total",
    "fuel_level_l", "fuel_consumed_l", "fuel_rate_lph", "fuel_pressure", "fuel_temp",
    "turbo_speed", "engine_load_pct", "gen_load_pct", "maintenance_due_h",
]

LT_KEYS = [f"{pfx}_{m}" for pfx, _ in PANELS for m in ("power", "voltage", "current", "frequency")]

RO_KEYS = [
    "status", "tds_ppm", "water_flow", "pressure", "ph", "salinity_ppm",
    "temperature_c", "ec_us_cm", "flow_total", "tds_online", "flow_online",
]

FIRE_KEYS = [
    "relay_online", "low_pressure", "high_pressure", "low_pressure_alarm", "high_pressure_alarm",
    "di1", "di2", "di3",
] + [f"cylinder_pressure_{i}" for i in range(1, 11)] + [f"fire_suppression_{i}_pressure" for i in range(1, 11)]


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


INTERNAL_EXCLUDED_KEYS = {
    "values", "claude_test_key", "sample_number", "sample_time_utc",
    "ping", "source", "modbus_errors", "energy_kwh_raw",
    "di_raw", "relay_1_di_raw", "relay_2_di_raw", "di3_alarm",
    "ai_mode", "ai_reason", "anomaly", "common_alarm_raw",
    "rssi", "snr", "uptime", "connected", "cpu", "memory", "disk",
}


def get_unit_for_key(key: str) -> str:
    """Return standard physical unit string for a telemetry key."""
    k = (key or "").lower()
    if any(x in k for x in ("status", "alarm", "state", "mode", "seq", "closed", "online", "comm_ok")):
        return ""
    if "freq" in k or "frequency" in k:
        return "Hz"
    if k.endswith("_voltage") or k.endswith("_v") or "_v_" in k or "voltage" in k or k in ("bus_v", "charge_alt_v", "starter_battery_v"):
        return "V"
    if k.endswith("_current") or k.endswith("_i") or "_i_" in k or "current" in k or k in ("battery_i", "charge_alt_i", "gen_i_neutral"):
        return "A"
    if k.endswith("_power") or k.endswith("_kw") or "_kw_" in k or "power_kw" in k or k in ("mains_kw",):
        return "kW"
    if "kva" in k:
        return "kVA"
    if "kvarh" in k:
        return "kVARh"
    if "kvar" in k:
        return "kVAR"
    if "kwh" in k or "energy" in k:
        return "kWh"
    if "temp" in k or "temperature" in k:
        return "°C"
    if any(x in k for x in ("fuel_pressure", "manifold_pressure", "coolant_pressure", "boost_pressure", "barometric", "kpa")):
        return "kPa"
    if "oil_pressure" in k or "cylinder_pressure" in k or k == "pressure" or "bar" in k:
        return "bar"
    if "rpm" in k or "speed" in k:
        return "RPM"
    if "pct" in k or "level_pct" in k or k in ("fuel_level", "health_score", "failure_risk_pct"):
        return "%"
    if k in ("fuel_level_l", "fuel_consumed_l") or (k.endswith("_l") and not k.endswith("_v_l")):
        return "L"
    if "lph" in k or "rate" in k:
        return "L/h"
    if "water_flow" in k:
        return "m³/h"
    if "flow_total" in k:
        return "m³"
    if "tds" in k or "salinity" in k:
        return "ppm"
    if "ec_us_cm" in k or "conductivity" in k:
        return "µS/cm"
    if k == "ph":
        return "pH"
    if "hours" in k or "run_hours" in k or "rul" in k or k.endswith("_h"):
        return "hours"
    if "starts" in k:
        return "starts"
    if "attempts" in k:
        return "attempts"
    if "deg" in k or "phase_deg" in k:
        return "°"
    if "rssi" in k or "dbm" in k:
        return "dBm"
    return ""


def normalize_value(key_or_raw: Any, raw_val: Any = None) -> str:
    """Normalize telemetry value with its exact physical unit & dimension."""
    if raw_val is not None:
        raw = raw_val
        key = str(key_or_raw).strip()
    else:
        raw = key_or_raw
        key = ""

    k = key.lower()

    if raw is None or raw == "":
        return "N/A"

    if k in INTERNAL_EXCLUDED_KEYS:
        return "EXCLUDE"

    # Booleans
    if isinstance(raw, bool):
        if "cylinder" in k or k.startswith("fire_suppression_"):
            return "Normal (Pressurized)" if raw is True else "ALERT: Discharged / Low Pressure"
        if "low_pressure" in k:
            return "Normal (Pressurized)" if raw is True else "ALERT: Low Pressure"
        if "high_pressure" in k:
            return "Normal (Pressurized)" if raw is True else "ALERT: High Pressure"
        if "alarm" in k:
            return "ALARM ACTIVE" if raw is True else "NORMAL (No Alarm)"
        if "online" in k:
            return "ONLINE" if raw is True else "OFFLINE"
        if k in ("anomaly",):
            return "ALERT DETECTED" if raw is True else "NORMAL"
        return "NORMAL / OK" if raw is True else "ALERT / OFF"

    s = str(raw).strip()
    s_lower = s.lower()

    if s_lower in ("n/a", "null", "none", "--"):
        return "N/A"

    # Sensor disconnect / standby codes
    if s_lower in ("error", "err", "32767", "65535", "32767.0", "65535.0", "3276.7"):
        if any(w in k for w in ("rpm", "speed", "oil", "coolant", "temp", "level")):
            return "Engine Standby (Stopped)"
        return "Standby / Inactive"

    # Known string enums
    if s_lower in ("running", "filtering", "auto", "manual", "standby"):
        return s.upper()
    if s_lower == "off":
        return "STANDBY (STOPPED)"
    if s_lower in ("gcb_closed", "closed"):
        return "CLOSED (ON-LOAD)"
    if s_lower in ("gcb_open", "open"):
        return "OPEN (DISCONNECTED)"

    try:
        num = float(raw)
        if num in (32767.0, 65535.0) or num >= 30000:
            if any(w in k for w in ("rpm", "speed", "oil", "coolant", "temp", "level")):
                return "Engine Standby (Stopped)"
            return "Standby / Inactive"

        # Discrete status integers
        if k in ("status", "dg_status", "engine_state"):
            return "STANDBY (STOPPED)" if num == 0 else "RUNNING"
        if k.startswith("fire_suppression_") and k.endswith("_pressure"):
            return "Normal (Pressurized)" if num == 0 else "ALERT: Discharged / Low Pressure"
        if k == "gcb_closed":
            return "CLOSED (ON-LOAD)" if num == 1 else "OPEN (DISCONNECTED)"
        if k == "mcb_closed":
            return "CLOSED (MAINS CONNECTED)" if num == 1 else "OPEN"
        if k == "mains_ok":
            return "HEALTHY (ONLINE)" if num == 1 else "GRID FAIL / OFFLINE"
        if k == "emergency_stop":
            return "NORMAL (Armed)" if num == 0 else "EMERGENCY STOP PRESSED"
        if k == "comm_ok":
            return "COMM OK" if num == 1 else "COMM FAULT"
        if k == "common_alarm":
            return "NORMAL (0)" if num == 0 else f"ALARM (Code {int(num)})"
        if k == "di1":
            return "NORMAL (Armed)" if num == 1 else "ABORT ACTIVATED"
        if k == "di2":
            return "NORMAL (Pressurized)" if num == 1 else "DISCHARGE DETECTED"
        if k == "di3":
            return "NORMAL (Standby)" if num == 1 else "MANUAL RELEASE PULLED"

        # Formatted physical values with units
        unit = get_unit_for_key(k)
        if unit == "V":
            return f"{num:.1f} V"
        if unit == "A":
            return f"{num:.1f} A"
        if unit == "kW":
            return f"{num:.1f} kW"
        if unit == "kVA":
            return f"{num:.1f} kVA"
        if unit == "kVAR":
            return f"{num:.1f} kVAR"
        if unit == "kVARh":
            return f"{num:,.1f} kVARh"
        if unit == "kWh":
            return f"{num:,.1f} kWh" if not num.is_integer() else f"{int(num):,} kWh"
        if unit == "Hz":
            return f"{num:.2f} Hz"
        if unit == "°C":
            return f"{num:.1f} °C"
        if unit == "kPa":
            return f"{num:.1f} kPa"
        if unit == "bar":
            return f"{num:.1f} bar"
        if unit == "RPM":
            return f"{int(round(num)):,} RPM"
        if unit == "%":
            return f"{num:.1f}%" if not num.is_integer() else f"{int(num)}%"
        if unit == "L":
            return f"{num:,.1f} L" if not num.is_integer() else f"{int(num):,} L"
        if unit == "L/h":
            return f"{num:.1f} L/h"
        if unit == "m³/h":
            return f"{num:.2f} m³/h"
        if unit == "m³":
            return f"{num:,.2f} m³"
        if unit == "ppm":
            return f"{int(round(num))} ppm"
        if unit == "µS/cm":
            return f"{num:.1f} µS/cm"
        if unit == "pH":
            return f"{num:.2f} pH"
        if unit == "hours":
            return f"{num:.1f} hours" if not num.is_integer() else f"{int(num)} hours"
        if unit == "starts":
            return f"{int(num)} starts"
        if unit == "attempts":
            return f"{int(num)} attempts"
        if unit == "°":
            return f"{num:.1f}°"
        if unit == "dBm":
            return f"{int(round(num))} dBm"

        if k == "power_factor":
            return f"{num:.2f}"

        if num.is_integer():
            return str(int(num))
        return f"{num:.2f}".rstrip("0").rstrip(".")

    except Exception:
        if s_lower in ("true", "online", "normal"):
            return "NORMAL / ONLINE"
        if s_lower in ("false", "offline"):
            return "OFFLINE"
        return s


def clean_alarm_text(raw_details: Any) -> str | None:
    if not raw_details:
        return None
    if isinstance(raw_details, dict):
        text = raw_details.get("data") or raw_details.get("message") or raw_details.get("msg") or raw_details.get("text") or str(raw_details)
    else:
        text = str(raw_details)

    text = re.sub(r"^\{['\"]data['\"]:\s*['\"]", "", text)
    text = re.sub(r"['\"]\}\s*$", "", text)
    text = re.sub(r"\$\{[^}]+\}\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _key_priority(key: str) -> int:
    k = key.lower()
    if k in ("status", "dg status", "operational status", "engine state"):
        return 0
    if "alarm" in k or "alert" in k:
        return 1
    if "power" in k or k.endswith("_kw") or "kw" in k:
        return 2
    if "voltage" in k or "_v" in k or " v" in k:
        return 3
    if "current" in k or "_i" in k or " a" in k:
        return 4
    if "freq" in k or "hz" in k:
        return 5
    if "battery" in k:
        return 6
    if "fuel" in k:
        return 7
    if "coolant" in k or "oil" in k or "temp" in k:
        return 8
    if "pressure" in k:
        return 9
    if "rpm" in k or "speed" in k:
        return 10
    if "tds" in k or "salinity" in k or "ec_us_cm" in k or "flow" in k or "ph" in k:
        return 11
    if "cylinder" in k or "gas" in k or "fire" in k:
        return 12
    if "hours" in k or "energy" in k or "kwh" in k:
        return 13
    return 20


def flatten_latest(ts: dict[str, Any]) -> tuple[dict[str, str], int | None]:
    values: dict[str, str] = {}
    latest_ts: int | None = None
    for key, points in (ts or {}).items():
        if not points:
            continue
        lowered_key = key.lower()
        if lowered_key in INTERNAL_EXCLUDED_KEYS:
            continue

        point = points[0]
        val = point.get("value")
        ts_val = point.get("ts")

        normalized = normalize_value(key, val)
        if normalized in ("N/A", "", "None", "EXCLUDE"):
            continue

        label = DISPLAY_MAP.get(key, key.replace("_", " ").title())
        values[label] = normalized
        if isinstance(ts_val, int):
            latest_ts = max(latest_ts or 0, ts_val)

    sorted_items = sorted(values.items(), key=lambda item: _key_priority(item[0]))
    return dict(sorted_items), latest_ts


async def fetch_latest_snapshot(
    client: ThingsBoardClient,
    device_id: UUID,
    device_name: str,
    device_type: str | None = None,
) -> dict[str, Any]:
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
