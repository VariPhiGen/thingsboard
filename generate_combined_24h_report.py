#!/usr/bin/env python3
import requests
import smtplib
import time
import json
import os
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

load_env_file()

SYSADMIN_USER = os.getenv("TB_USER", "sysadmin@thingsboard.org")
SYSADMIN_PASS = os.getenv("TB_PASS", "sysadmin")

# Email SMTP Settings
SMTP_SERVER = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "smtpout.secureserver.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "information@variphi.com")
SMTP_PASSWORD = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER
REPORT_RECIPIENTS = os.getenv("REPORT_RECIPIENTS", "shivamskr151@gmail.com,muskan.betla@gmail.com,msdeo990@gmail.com,wr.gowthamvarma@gmail.com")

_RESOLVED_BASE_URL = None

def get_base_url():
    global _RESOLVED_BASE_URL
    if _RESOLVED_BASE_URL:
        return _RESOLVED_BASE_URL

    candidates = [
        "http://172.17.0.1:9091",
        "http://172.20.0.1:9091",
        os.getenv("TB_BASE_URL", "").strip(),
        "http://localhost:9091"
    ]
    candidates = [u for u in candidates if u]

    for base in candidates:
        url = f"{base}/api/auth/login"
        payload = {"username": SYSADMIN_USER, "password": SYSADMIN_PASS}
        try:
            res = requests.post(url, json=payload, headers={"Accept": "application/json"}, timeout=3)
            if res.status_code == 200:
                _RESOLVED_BASE_URL = base
                return base
        except Exception:
            pass

    _RESOLVED_BASE_URL = "http://localhost:9091"
    return _RESOLVED_BASE_URL

def login(username, password):
    base = get_base_url()
    url = f"{base}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"}, timeout=5)
    response.raise_for_status()
    return response.json()['token']

def safe_float(val, default=0.0):
    try:
        if val is None or val == 'N/A' or val == '':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def get_tenant_headers():
    base = get_base_url()
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    ten_id = requests.get(f"{base}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    user_id = requests.get(f"{base}/api/tenant/{ten_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{base}/api/user/{user_id}/token", headers=sys_headers).json()['token']
    return {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

def fetch_master_devices_summary():
    base = get_base_url()
    headers = get_tenant_headers()
    devices = requests.get(f"{base}/api/tenant/devices?pageSize=100&page=0", headers=headers).json()['data']
    
    summary = []
    now_ts = int(time.time() * 1000)
    start_24h_ts = now_ts - (24 * 3600 * 1000)

    for dev in devices:
        dev_id = dev['id']['id']
        name = dev['name']
        dev_type = dev.get('type', 'DEFAULT')

        # Attributes
        attrs_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/attributes", headers=headers)
        attrs = attrs_res.json() if attrs_res.ok else []
        attr_dict = {a['key']: a['value'] for a in attrs}
        
        is_active = attr_dict.get('active', False)
        last_act = attr_dict.get('lastActivityTime', 0)
        last_act_str = datetime.fromtimestamp(last_act/1000).strftime('%Y-%m-%d %H:%M:%S') if last_act else "No activity"

        # Latest Telemetry Keys
        keys_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/keys/timeseries", headers=headers)
        keys = keys_res.json() if keys_res.ok else []
        
        tel_data = {}
        agg_24h = {}

        if keys:
            k_str = ",".join(keys)
            vals_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}", headers=headers)
            if vals_res.ok:
                raw_vals = vals_res.json()
                for k, v in raw_vals.items():
                    if v:
                        tel_data[k] = v[0]['value']

            # Full 24-Hour Aggregations (AVG, MAX, MIN)
            try:
                avg_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={start_24h_ts}&endTs={now_ts}&interval=86400000&agg=AVG", headers=headers)
                if avg_res.ok:
                    for k, v in avg_res.json().items():
                        if v and v[0].get('value') is not None:
                            try: agg_24h[f"{k}_24h_avg"] = round(float(v[0]['value']), 1)
                            except: pass

                max_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={start_24h_ts}&endTs={now_ts}&interval=86400000&agg=MAX", headers=headers)
                if max_res.ok:
                    for k, v in max_res.json().items():
                        if v and v[0].get('value') is not None:
                            try: agg_24h[f"{k}_24h_max"] = round(float(v[0]['value']), 1)
                            except: pass

                min_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={start_24h_ts}&endTs={now_ts}&interval=86400000&agg=MIN", headers=headers)
                if min_res.ok:
                    for k, v in min_res.json().items():
                        if v and v[0].get('value') is not None:
                            try: agg_24h[f"{k}_24h_min"] = round(float(v[0]['value']), 1)
                            except: pass
            except Exception as e:
                print(f"Aggregation error for {name}: {e}")

        # Alarms
        alarms_res = requests.get(f"{base}/api/alarm/DEVICE/{dev_id}?pageSize=50&page=0&status=ACTIVE_UNACK,ACTIVE_ACK", headers=headers)
        active_alarms = alarms_res.json()['data'] if alarms_res.ok else []

        summary.append({
            "id": dev_id,
            "name": name,
            "type": dev_type,
            "is_active": is_active,
            "last_activity": last_act_str,
            "telemetry": tel_data,
            "agg_24h": agg_24h,
            "alarms_count": len(active_alarms),
            "active_alarms": [a.get('type') for a in active_alarms]
        })

    return summary

# ==============================================================================
# SINGLE COMBINED 24-HOUR INFRASTRUCTURE REPORT GENERATOR
# ==============================================================================
def generate_combined_24h_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    total_devices = len(devices_summary)
    active_devices = sum(1 for d in devices_summary if d['is_active'])
    total_alarms = sum(d['alarms_count'] for d in devices_summary)

    # --------------------------------------------------------------------------
    # SECTION 1: DG SETS 24H BREAKDOWN
    # --------------------------------------------------------------------------
    dg_devices = [d for d in devices_summary if "DG Set" in d['name'] or d['type'] == 'woodward_kg1500']
    total_dg = len(dg_devices)
    active_dg = sum(1 for d in dg_devices if d['is_active'])
    running_dg = sum(1 for d in dg_devices if d['telemetry'].get('dg_status') == 'RUNNING' or str(d['telemetry'].get('engine_rpm', 0)) > '100')
    total_energy_dg = sum(safe_float(d['telemetry'].get('energy_kwh')) for d in dg_devices)

    dg_rows = ""
    for d in dg_devices:
        status_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">ACTIVE</span>' if d['is_active'] else '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">OFFLINE</span>'
        tel = d['telemetry']
        agg = d['agg_24h']
        
        coolant = tel.get('coolant_temp', 'N/A')
        coolant_disp = f"{coolant} °C" if coolant != '32767' and coolant != 'N/A' else "Sensor Fault / Offline"
        oil_p = tel.get('oil_pressure', 'N/A')
        oil_p_disp = f"{oil_p} bar" if oil_p != '32767' and oil_p != 'N/A' else "Sensor Fault / Offline"

        fuel = f"{tel.get('fuel_level', 'N/A')}%"
        fuel_avg = f"{agg.get('fuel_level_24h_avg', 'N/A')}%"
        fuel_min = f"{agg.get('fuel_level_24h_min', 'N/A')}%"
        bat_v = f"{tel.get('battery_voltage', 'N/A')} V"
        pwr = f"{tel.get('power_kw', '0')} kW"
        pwr_max = f"{agg.get('power_kw_24h_max', '0')} kW"
        energy = f"{tel.get('energy_kwh', '0')} kWh"
        run_h = f"{tel.get('run_hours', '0')} hrs"
        starts = tel.get('engine_starts', '0')
        dg_state = tel.get('dg_status', 'STOPPED')

        dg_state_badge = f'<span style="background-color:#00897b;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{dg_state}</span>' if dg_state == 'RUNNING' else f'<span style="background-color:#757575;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{dg_state}</span>'

        dg_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:10px;font-weight:bold;color:#0d47a1;">{d['name']}<br/>{status_badge}</td>
            <td style="padding:10px;text-align:center;">{dg_state_badge}</td>
            <td style="padding:10px;line-height:1.5;">
                ⚡ <b>Live Power:</b> {pwr} (24h Max: {pwr_max})<br/>
                🔋 <b>Cumulative Energy:</b> {energy}<br/>
                ⏱️ <b>Run Hours:</b> {run_h} | 🔄 <b>Starts:</b> {starts}
            </td>
            <td style="padding:10px;line-height:1.5;">
                ⛽ <b>Fuel Level:</b> {fuel}<br/>
                📊 <b>24h Avg Fuel:</b> {fuel_avg} (Min: {fuel_min})<br/>
                🔋 <b>Battery Voltage:</b> {bat_v}
            </td>
            <td style="padding:10px;line-height:1.5;">
                🌡️ <b>Coolant Temp:</b> {coolant_disp}<br/>
                ⚙️ <b>Oil Pressure:</b> {oil_p_disp}
            </td>
            <td style="padding:10px;color:#757575;font-size:11px;">{d['last_activity']}</td>
        </tr>
        """

    # --------------------------------------------------------------------------
    # SECTION 2: LT PANELS 24H BREAKDOWN
    # --------------------------------------------------------------------------
    lt_master = next((d for d in devices_summary if "LT Panel" in d['name'] or d['type'] == 'LT Panel Master Profile'), None)
    panels_def = [
        ("EVM Charger", "EVM_Charger"),
        ("Electrical Room 1", "Electrical_room_1"),
        ("UPS Room 1", "UPS_Room_1"),
        ("Transformer 1", "Transformer_1"),
        ("Transformer 2", "Transformer_2"),
        ("Transformer 3", "Transformer_3"),
        ("Fire Fighting Wall", "Fire_fighting_wall")
    ]
    lt_tel = lt_master['telemetry'] if lt_master else {}
    lt_agg = lt_master['agg_24h'] if lt_master else {}

    total_lt_kw = sum(safe_float(lt_tel.get(f"{prefix}_power")) for _, prefix in panels_def)
    active_lt_circuits = sum(1 for _, prefix in panels_def if safe_float(lt_tel.get(f"{prefix}_voltage")) > 0)

    lt_rows = ""
    for name, prefix in panels_def:
        v = lt_tel.get(f"{prefix}_voltage", "N/A")
        i = lt_tel.get(f"{prefix}_current", "N/A")
        p = lt_tel.get(f"{prefix}_power", "N/A")
        freq = lt_tel.get(f"{prefix}_frequency", "N/A")

        p_avg = lt_agg.get(f"{prefix}_power_24h_avg", "N/A")
        p_max = lt_agg.get(f"{prefix}_power_24h_max", "N/A")
        v_max = lt_agg.get(f"{prefix}_voltage_24h_max", "N/A")

        has_data = v != "N/A" and safe_float(v) > 0
        panel_status = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">LIVE ENERGIZED</span>' if has_data else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">STANDBY</span>'

        lt_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:10px;font-weight:bold;color:#1b5e20;">{name}</td>
            <td style="padding:10px;text-align:center;">{panel_status}</td>
            <td style="padding:10px;font-weight:bold;color:#2e7d32;">{p} kW</td>
            <td style="padding:10px;">{v} V</td>
            <td style="padding:10px;">{i} A</td>
            <td style="padding:10px;">{freq} Hz</td>
            <td style="padding:10px;line-height:1.5;">
                📊 <b>24h Avg Power:</b> {p_avg} kW<br/>
                ⚡ <b>24h Max Power:</b> {p_max} kW (Max V: {v_max} V)
            </td>
        </tr>
        """

    # --------------------------------------------------------------------------
    # SECTION 3: FIRE SUPPRESSION 24H BREAKDOWN
    # --------------------------------------------------------------------------
    fire_dev = next((d for d in devices_summary if "Fire" in d['name'] or d['type'] == 'LT Panel Fire Profile'), None)
    fire_tel = fire_dev['telemetry'] if fire_dev else {}
    
    relay_online = str(fire_tel.get('relay_online', 'true')).lower() == 'true'
    low_press_ok = str(fire_tel.get('low_pressure', 'true')).lower() == 'true'
    high_press_ok = str(fire_tel.get('high_pressure', 'true')).lower() == 'true'
    cyl1_ok = str(fire_tel.get('cylinder_pressure_1', 'true')).lower() == 'true'
    cyl2_ok = str(fire_tel.get('cylinder_pressure_2', 'true')).lower() == 'true'
    cyl3_ok = str(fire_tel.get('cylinder_pressure_3', 'true')).lower() == 'true'

    fire_rows = ""
    for i in range(1, 4):
        cyl_val = str(fire_tel.get(f"cylinder_pressure_{i}", 'true')).lower() == 'true'
        cyl_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:bold;">PRESSURE NORMAL</span>' if cyl_val else '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:bold;">PRESSURE LOW</span>'

        di_val = str(fire_tel.get(f"di{i}", 'true')).lower() == 'true'
        di_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:bold;">CLOSED / NORMAL</span>' if di_val else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:bold;">OPEN / CHECK</span>'

        fire_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:10px;font-weight:bold;color:#c62828;">Fire Separation Zone {i}</td>
            <td style="padding:10px;text-align:center;">{cyl_badge}</td>
            <td style="padding:10px;text-align:center;">{di_badge}</td>
            <td style="padding:10px;">Gas Pressure Sensor & Alarm Loop</td>
            <td style="padding:10px;color:#4caf50;font-weight:bold;">Operational (24h Monitored)</td>
        </tr>
        """

    # --------------------------------------------------------------------------
    # SECTION 4: RO PLANT SYSTEM 24H SUMMARY
    # --------------------------------------------------------------------------
    ro_dev = next((d for d in devices_summary if "RO Plant" in d['name'] or d['type'] == 'RO System Profile'), None)
    ro_tel = ro_dev['telemetry'] if ro_dev else {}
    ro_agg = ro_dev['agg_24h'] if ro_dev else {}
    
    ro_status = ro_tel.get('status', 'OFFLINE')
    ro_tds = ro_tel.get('tds', 'N/A')
    ro_tds_avg = ro_agg.get('tds_24h_avg', 'N/A')
    ro_tds_max = ro_agg.get('tds_24h_max', 'N/A')
    ro_flow = ro_tel.get('water_flow', 'N/A')
    ro_flow_avg = ro_agg.get('water_flow_24h_avg', 'N/A')
    ro_press = ro_tel.get('pressure', 'N/A')
    ro_ph = ro_tel.get('ph', '7.4')

    ro_badge = f'<span style="background-color:#0288d1;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{ro_status}</span>'

    # Master HTML Structure
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily 24-Hour Master Infrastructure Operations Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f2f4f8; margin: 0; padding: 20px;">
        <div style="max-width: 980px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.12);">
            
            <!-- MASTER HEADER -->
            <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%); color: #ffffff; padding: 30px;">
                <h1 style="margin: 0; font-size: 25px; letter-spacing: 0.5px;">🏢 Master Infrastructure 24-Hour Operations Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Report Period: Past 24 Hours | Date: {date_str} | Generated: {time_str}</p>
            </div>

            <!-- EXECUTIVE OVERVIEW CARDS -->
            <div style="display: flex; padding: 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 8px; border: 1px solid #cbd5e1;">
                    <div style="font-size: 26px; font-weight: bold; color: #0f172a;">{total_devices}</div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase;">Master Devices</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 8px; border: 1px solid #cbd5e1;">
                    <div style="font-size: 26px; font-weight: bold; color: #16a34a;">{active_devices}</div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase;">Active Systems</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 8px; border: 1px solid #cbd5e1;">
                    <div style="font-size: 26px; font-weight: bold; color: #2563eb;">{total_energy_dg:.1f} kWh</div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase;">24h DG Energy</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 8px; border: 1px solid #cbd5e1;">
                    <div style="font-size: 26px; font-weight: bold; color: #059669;">{total_lt_kw:.1f} kW</div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase;">Live LT Load</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 8px; border: 1px solid #cbd5e1;">
                    <div style="font-size: 26px; font-weight: bold; color: {'#dc2626' if total_alarms > 0 else '#16a34a'};">{total_alarms}</div>
                    <div style="font-size: 11px; color: #64748b; text-transform: uppercase;">Active System Alerts</div>
                </div>
            </div>

            <!-- ========================================================================= -->
            <!-- SECTION 1: DIESEL GENERATOR (DG SETS) -->
            <!-- ========================================================================= -->
            <div style="padding: 24px; border-bottom: 2px solid #e2e8f0;">
                <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 16px;">
                    <h2 style="margin: 0; color: #1e3a8a; font-size: 18px;">⚡ 1. Diesel Generator (DG Sets) Operations & 24h Summary</h2>
                    <span style="font-size: 12px; color: #64748b; font-weight: bold;">{active_dg}/{total_dg} DG Sets Active | {running_dg} Running</span>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #eff6ff; text-align: left; border-bottom: 2px solid #bfdbfe;">
                            <th style="padding: 10px;">DG Unit</th>
                            <th style="padding: 10px; text-align:center;">Status</th>
                            <th style="padding: 10px;">Power & 24h Energy</th>
                            <th style="padding: 10px;">Fuel Level & Battery</th>
                            <th style="padding: 10px;">Engine Health</th>
                            <th style="padding: 10px;">Last Sync</th>
                        </tr>
                    </thead>
                    <tbody>
                        {dg_rows}
                    </tbody>
                </table>
            </div>

            <!-- ========================================================================= -->
            <!-- SECTION 2: LOW VOLTAGE (LT) PANELS -->
            <!-- ========================================================================= -->
            <div style="padding: 24px; border-bottom: 2px solid #e2e8f0;">
                <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #16a34a; padding-bottom: 8px; margin-bottom: 16px;">
                    <h2 style="margin: 0; color: #14532d; font-size: 18px;">🔌 2. Low Voltage (LT) Panels Electrical & 24h Load Distribution</h2>
                    <span style="font-size: 12px; color: #64748b; font-weight: bold;">{active_lt_circuits}/7 Circuits Energized | Total Load: {total_lt_kw:.1f} kW</span>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f0fdf4; text-align: left; border-bottom: 2px solid #bbf7d0;">
                            <th style="padding: 10px;">Sub-Panel</th>
                            <th style="padding: 10px; text-align:center;">State</th>
                            <th style="padding: 10px;">Live Load (kW)</th>
                            <th style="padding: 10px;">Voltage (V)</th>
                            <th style="padding: 10px;">Current (A)</th>
                            <th style="padding: 10px;">Freq (Hz)</th>
                            <th style="padding: 10px;">24h Aggregation Metrics</th>
                        </tr>
                    </thead>
                    <tbody>
                        {lt_rows}
                    </tbody>
                </table>
            </div>

            <!-- ========================================================================= -->
            <!-- SECTION 3: FIRE SUPPRESSION SYSTEM -->
            <!-- ========================================================================= -->
            <div style="padding: 24px; border-bottom: 2px solid #e2e8f0;">
                <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #dc2626; padding-bottom: 8px; margin-bottom: 16px;">
                    <h2 style="margin: 0; color: #7f1d1d; font-size: 18px;">🧯 3. Fire Suppression System & 24h Safety Status</h2>
                    <span style="font-size: 12px; color: #64748b; font-weight: bold;">Relay: {'ONLINE' if relay_online else 'OFFLINE'} | Cylinders: {'3/3 OK' if (cyl1_ok and cyl2_ok and cyl3_ok) else 'CHECK'}</span>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #fef2f2; text-align: left; border-bottom: 2px solid #fecaca;">
                            <th style="padding: 10px;">Separation Zone</th>
                            <th style="padding: 10px; text-align:center;">Cylinder Gas Pressure</th>
                            <th style="padding: 10px; text-align:center;">Digital Input Loop</th>
                            <th style="padding: 10px;">Sensor Type</th>
                            <th style="padding: 10px;">Operational Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {fire_rows}
                    </tbody>
                </table>
            </div>

            <!-- ========================================================================= -->
            <!-- SECTION 4: RO PLANT WATER TREATMENT -->
            <!-- ========================================================================= -->
            <div style="padding: 24px;">
                <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #0288d1; padding-bottom: 8px; margin-bottom: 16px;">
                    <h2 style="margin: 0; color: #075985; font-size: 18px;">💧 4. RO Plant Water Treatment & 24h Quality Report</h2>
                    <span style="font-size: 12px; color: #64748b; font-weight: bold;">Status: {ro_badge}</span>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f0f9ff; text-align: left; border-bottom: 2px solid #bae6fd;">
                            <th style="padding: 10px;">Parameter</th>
                            <th style="padding: 10px;">Live Telemetry Reading</th>
                            <th style="padding: 10px;">24h Average Reading</th>
                            <th style="padding: 10px;">24h Maximum Peak</th>
                            <th style="padding: 10px;">Quality Compliance</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #e0e0e0;">
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">TDS (Total Dissolved Solids)</td>
                            <td style="padding:10px;font-weight:bold;">{ro_tds} ppm</td>
                            <td style="padding:10px;">{ro_tds_avg} ppm</td>
                            <td style="padding:10px;">{ro_tds_max} ppm</td>
                            <td style="padding:10px;color:#16a34a;font-weight:bold;">Optimal (&lt; 200 ppm)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e0e0e0;">
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">Permeate Water Flow Rate</td>
                            <td style="padding:10px;font-weight:bold;">{ro_flow} L/min</td>
                            <td style="padding:10px;">{ro_flow_avg} L/min</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#16a34a;font-weight:bold;">Normal Flow</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e0e0e0;">
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">RO Membrane Pressure</td>
                            <td style="padding:10px;font-weight:bold;">{ro_press} psi</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#16a34a;font-weight:bold;">Normal Pressure</td>
                        </tr>
                        <tr>
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">pH Level</td>
                            <td style="padding:10px;font-weight:bold;">{ro_ph}</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#16a34a;font-weight:bold;">Balanced (6.5 - 8.5)</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- FOOTER -->
            <div style="background: #e2e8f0; padding: 20px; text-align: center; font-size: 12px; color: #475569; border-top: 1px solid #cbd5e1;">
                Automated 24-Hour Master Infrastructure Operations Report • Virtuoso NetSoft Operations Center
            </div>
        </div>
    </body>
    </html>
    """
    return html

def get_pdf_generator_url():
    candidates = [
        "http://pdf-generator:3005",
        "http://172.17.0.1:3005",
        "http://172.20.0.1:3005",
        "http://localhost:3005"
    ]
    for u in candidates:
        try:
            r = requests.get(f"{u}/health", timeout=2)
            if r.ok:
                return u
        except Exception:
            pass
    return "http://localhost:3005"

def convert_html_to_pdf(html_content):
    try:
        base = get_pdf_generator_url()
        url = f"{base}/render-raw-html-pdf"
        res = requests.post(url, json={"html": html_content}, timeout=60)
        if res.status_code == 200:
            return res.content
        print(f"⚠️ PDF generator returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"⚠️ PDF generation error: {e}")
    return None

def send_combined_email_report(html_content, recipients_override=None, attach_pdf=True):
    recipients_str = recipients_override or REPORT_RECIPIENTS
    if not recipients_str:
        print("⚠️ No recipients defined!")
        return False

    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        return False

    if not SMTP_USER or not SMTP_PASSWORD:
        print("⚠️ SMTP credentials missing!")
        return False

    sender_from = SMTP_FROM or SMTP_USER
    msg = MIMEMultipart("mixed")
    date_str = datetime.now().strftime('%d %b %Y')
    date_fn = datetime.now().strftime('%Y%m%d')

    msg["Subject"] = f"📑 Daily 24-Hour Master Infrastructure Report — {date_str}"
    msg["From"] = f"ThingsBoard Master Operations <{sender_from}>"
    msg["To"] = ", ".join(recipients)

    msg_body = MIMEMultipart("alternative")
    msg_body.attach(MIMEText(html_content, "html"))
    msg.attach(msg_body)

    if attach_pdf:
        print("Rendering PDF attachment via Chromium PDF engine...")
        pdf_bytes = convert_html_to_pdf(html_content)
        if pdf_bytes:
            from email.mime.application import MIMEApplication
            pdf_filename = f"Master_Infrastructure_24h_Report_{date_fn}.pdf"
            att = MIMEApplication(pdf_bytes, _subtype="pdf")
            att.add_header("Content-Disposition", "attachment", filename=pdf_filename)
            msg.attach(att)
            print(f"📎 PDF Attachment successfully added: {pdf_filename} ({len(pdf_bytes)} bytes)")
        else:
            print("⚠️ Skipping PDF attachment due to generation error.")

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20)
            server.ehlo()
            server.starttls()
            
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(sender_from, recipients, msg.as_string())
        server.quit()
        print(f"✅ Combined 24h Infrastructure PDF & HTML Email Sent to {len(recipients)} recipient(s): {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ Failed to send combined report email: {e}")
        return False

def main():
    args = sys.argv[1:]
    
    print("Fetching master devices summary from ThingsBoard...")
    summary = fetch_master_devices_summary()
    html_report = generate_combined_24h_report(summary)

    if "--preview" in args:
        preview_path = "/home/ubuntu/thingsboard/combined_24h_report_preview.html"
        pdf_preview_path = "/home/ubuntu/thingsboard/combined_24h_report_preview.pdf"

        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_report)
        print(f"✅ HTML Combined 24h Report Preview saved to: {preview_path}")

        print("Generating PDF Preview file...")
        pdf_bytes = convert_html_to_pdf(html_report)
        if pdf_bytes:
            with open(pdf_preview_path, "wb") as f:
                f.write(pdf_bytes)
            print(f"✅ PDF Combined 24h Report Preview saved to: {pdf_preview_path}")

    if "--send-now" in args:
        recipients = None
        for a in args:
            if a.startswith("--to="):
                recipients = a.split("=")[1]
        send_combined_email_report(html_report, recipients, attach_pdf=True)

    if not args:
        print("\nUsage:")
        print("  python3 generate_combined_24h_report.py --preview              (Generates HTML and PDF preview files)")
        print("  python3 generate_combined_24h_report.py --send-now             (Sends combined HTML email with PDF attachment)")
        print("  python3 generate_combined_24h_report.py --send-now --to=a@b.com (Sends report with PDF to specific email)")

if __name__ == "__main__":
    main()
