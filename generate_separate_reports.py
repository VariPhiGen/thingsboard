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

DEFAULT_BASE_URLS = [
    os.getenv("TB_BASE_URL", "").strip(),
    "http://localhost:9091",
    "http://172.17.0.1:9091",
    "http://host.docker.internal:9091",
    "http://virtuoso-tb-mytb-1:8080"
]
DEFAULT_BASE_URLS = [u for u in DEFAULT_BASE_URLS if u]
BASE_URL = DEFAULT_BASE_URLS[0]

SYSADMIN_USER = os.getenv("TB_USER", "sysadmin@thingsboard.org")
SYSADMIN_PASS = os.getenv("TB_PASS", "sysadmin")
# Preferred: direct tenant-admin login (no sysadmin impersonation needed).
TENANT_USER = os.getenv("TB_TENANT_USER", "").strip()
TENANT_PASS = os.getenv("TB_TENANT_PASS", "")

# Email SMTP Settings
SMTP_SERVER = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "smtpout.secureserver.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "information@variphi.com")
SMTP_PASSWORD = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER
REPORT_RECIPIENTS = os.getenv("REPORT_RECIPIENTS", "information@variphi.com,muskan.betla@gmail.com,wr.gowthamvarma@gmail.com,sharavan.m@delhivery.com,shahill.suswal@delhivery.com,nitish@variphi.com,msdeo@variphi.com,shivam@variphi.com")

_RESOLVED_BASE_URL = None

def get_base_url():
    global _RESOLVED_BASE_URL
    if _RESOLVED_BASE_URL:
        return _RESOLVED_BASE_URL

    candidates = [
        os.getenv("TB_BASE_URL", "").strip().rstrip("/"),
        "http://172.17.0.1:9091",
        "http://172.20.0.1:9091",
        "http://localhost:9091"
    ]
    candidates = [u for u in candidates if u]

    for base in candidates:
        url = f"{base}/api/auth/login"
        if TENANT_USER and TENANT_PASS:
            payload = {"username": TENANT_USER, "password": TENANT_PASS}
        else:
            payload = {"username": SYSADMIN_USER, "password": SYSADMIN_PASS}
        try:
            res = requests.post(url, json=payload, headers={"Accept": "application/json"}, timeout=10)
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
        if val is None or val == 'N/A':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def get_tenant_headers():
    base = get_base_url()
    if TENANT_USER and TENANT_PASS:
        tenant_token = login(TENANT_USER, TENANT_PASS)
        return {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
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

            # 24-Hour Aggregations (AVG, MAX)
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
# REPORT 1: DG SETS REPORT GENERATOR
# ==============================================================================
def generate_dg_set_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    dg_devices = [d for d in devices_summary if "DG Set" in d['name'] or d['type'] == 'woodward_kg1500']
    total_dg = len(dg_devices)
    active_dg = sum(1 for d in dg_devices if d['is_active'])
    running_dg = sum(1 for d in dg_devices if d['telemetry'].get('dg_status') == 'RUNNING' or str(d['telemetry'].get('engine_rpm', 0)) > '100')
    total_alarms = sum(d['alarms_count'] for d in dg_devices)
    total_energy = sum(safe_float(d['telemetry'].get('energy_kwh')) for d in dg_devices)

    rows_html = ""
    for d in dg_devices:
        status_badge = '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:bold;">ACTIVE</span>' if d['is_active'] else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:bold;">OFFLINE</span>'
        
        tel = d['telemetry']
        agg = d['agg_24h']
        
        rpm = tel.get('engine_rpm', 'N/A')
        coolant = tel.get('coolant_temp', 'N/A')
        coolant_disp = f"{coolant} °C" if coolant != '32767' and coolant != 'N/A' else "N/A (Sensor Offline)"
        oil_p = tel.get('oil_pressure', 'N/A')
        oil_p_disp = f"{oil_p} bar" if oil_p != '32767' and oil_p != 'N/A' else "N/A (Sensor Offline)"
        
        fuel = f"{tel.get('fuel_level', 'N/A')}%"
        fuel_avg = f"{agg.get('fuel_level_24h_avg', 'N/A')}%"
        bat_v = f"{tel.get('battery_voltage', 'N/A')} V"
        pwr = f"{tel.get('power_kw', '0')} kW"
        energy = f"{tel.get('energy_kwh', '0')} kWh"
        run_h = f"{tel.get('run_hours', '0')} hrs"
        starts = tel.get('engine_starts', '0')
        dg_state = tel.get('dg_status', 'STOPPED')

        dg_state_badge = f'<span style="background-color:#00897b;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{dg_state}</span>' if dg_state == 'RUNNING' else f'<span style="background-color:#757575;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{dg_state}</span>'

        alarms_str = f'<b style="color:#f44336;">{d["alarms_count"]} Active Alerts</b>' if d['alarms_count'] > 0 else '<span style="color:#4caf50;">Normal</span>'

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#0d47a1;">{d['name']}<br/>{status_badge}</td>
            <td style="padding:12px;text-align:center;">{dg_state_badge}</td>
            <td style="padding:12px;line-height:1.6;">
                ⚡ <b>Power:</b> {pwr} | 🔋 <b>Energy:</b> {energy}<br/>
                ⏱️ <b>Run Hours:</b> {run_h} | 🔄 <b>Starts:</b> {starts}
            </td>
            <td style="padding:12px;line-height:1.6;">
                ⛽ <b>Fuel Level:</b> {fuel} (24h Avg: {fuel_avg})<br/>
                🔋 <b>Battery Voltage:</b> {bat_v}
            </td>
            <td style="padding:12px;line-height:1.6;">
                🌡️ <b>Coolant Temp:</b> {coolant_disp}<br/>
                ⚙️ <b>Oil Pressure:</b> {oil_p_disp}
            </td>
            <td style="padding:12px;text-align:center;">{alarms_str}</td>
            <td style="padding:12px;color:#757575;font-size:12px;">{d['last_activity']}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily DG Sets Operations & Health Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #0d47a1 0%, #1976d2 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">⚡ Daily Diesel Generator (DG Set) Operations Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str}</p>
            </div>

            <!-- Executive Summary Cards -->
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #0d47a1;">{total_dg}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Total DG Sets</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #4caf50;">{active_dg}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Active / Online</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #00897b;">{running_dg}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Currently Running</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #ff9800;">{total_energy:.1f} kWh</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Total Energy Generated</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: {'#f44336' if total_alarms > 0 else '#4caf50'};">{total_alarms}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Active Alarms</div>
                </div>
            </div>

            <!-- Breakdown Table -->
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 DG Sets Detailed Operational Breakdown</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #e3f2fd; text-align: left; border-bottom: 2px solid #bbdefb;">
                            <th style="padding: 10px;">DG Set Name</th>
                            <th style="padding: 10px; text-align:center;">State</th>
                            <th style="padding: 10px;">Power & Energy</th>
                            <th style="padding: 10px;">Fuel & Battery</th>
                            <th style="padding: 10px;">Engine Sensors</th>
                            <th style="padding: 10px; text-align:center;">Alarms</th>
                            <th style="padding: 10px;">Last Sync</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated DG Set Operations Report • Virtuoso NetSoft Infrastructure Management
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ==============================================================================
# REPORT 2: LT PANELS REPORT GENERATOR
# ==============================================================================
def generate_lt_panels_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

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

    tel = lt_master['telemetry'] if lt_master else {}
    agg = lt_master['agg_24h'] if lt_master else {}
    is_active = lt_master['is_active'] if lt_master else False

    total_panels = len(panels_def)
    active_panels = sum(1 for _, prefix in panels_def if f"{prefix}_voltage" in tel and safe_float(tel.get(f"{prefix}_voltage")) > 0)
    total_kw = sum(safe_float(tel.get(f"{prefix}_power")) for _, prefix in panels_def)

    rows_html = ""
    for name, prefix in panels_def:
        v = tel.get(f"{prefix}_voltage", "N/A")
        i = tel.get(f"{prefix}_current", "N/A")
        p = tel.get(f"{prefix}_power", "N/A")
        freq = tel.get(f"{prefix}_frequency", "N/A")

        p_avg = agg.get(f"{prefix}_power_24h_avg", "N/A")
        p_max = agg.get(f"{prefix}_power_24h_max", "N/A")
        v_max = agg.get(f"{prefix}_voltage_24h_max", "N/A")

        has_data = v != "N/A" and safe_float(v) > 0
        panel_status = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:bold;">LIVE</span>' if has_data else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:bold;">STANDBY / NO POWER</span>'

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#2e7d32;">{name}</td>
            <td style="padding:12px;text-align:center;">{panel_status}</td>
            <td style="padding:12px;font-weight:bold;color:#1b5e20;">{p} kW</td>
            <td style="padding:12px;">{v} V</td>
            <td style="padding:12px;">{i} A</td>
            <td style="padding:12px;">{freq} Hz</td>
            <td style="padding:12px;line-height:1.5;">
                📊 <b>Avg Power:</b> {p_avg} kW<br/>
                ⚡ <b>Max Power:</b> {p_max} kW (Max V: {v_max} V)
            </td>
        </tr>
        """

    master_badge = '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">MASTER ONLINE</span>' if is_active else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">MASTER OFFLINE</span>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily LT Panels Electrical Load Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #1b5e20 0%, #388e3c 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">🔌 Daily Low Voltage (LT) Panels Power & Load Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Status: {master_badge}</p>
            </div>

            <!-- Executive Summary Cards -->
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #1b5e20;">{total_panels}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Sub-Panels Monitored</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #4caf50;">{active_panels}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Circuits Energized</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #2e7d32;">{total_kw:.1f} kW</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Total Live Power Load</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #00897b;">50.0 Hz</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Grid Frequency</div>
                </div>
            </div>

            <!-- Breakdown Table -->
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 LT Sub-Panels Electrical Parameters</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #e8f5e9; text-align: left; border-bottom: 2px solid #c8e6c9;">
                            <th style="padding: 10px;">Sub-Panel Name</th>
                            <th style="padding: 10px; text-align:center;">State</th>
                            <th style="padding: 10px;">Live Power (kW)</th>
                            <th style="padding: 10px;">Voltage (V)</th>
                            <th style="padding: 10px;">Current (A)</th>
                            <th style="padding: 10px;">Frequency</th>
                            <th style="padding: 10px;">24h Aggregations</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated LT Panels Electrical Summary • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ==============================================================================
# REPORT 3: FIRE SUPPRESSION REPORT GENERATOR
# ==============================================================================
def generate_fire_suppression_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    fire_dev = next((d for d in devices_summary if ("Fire" in d['name'] and "UPS Room 2" not in d['name']) or d['name'] == 'Fire Suppression'), None)

    tel = fire_dev['telemetry'] if fire_dev else {}
    alarms_count = fire_dev['alarms_count'] if fire_dev else 0

    relay_online = str(tel.get('relay_online', 'true')).lower() == 'true'
    low_press_ok = str(tel.get('low_pressure', 'true')).lower() == 'true'
    high_press_ok = str(tel.get('high_pressure', 'true')).lower() == 'true'
    cyl_statuses = [str(tel.get(f'cylinder_pressure_{i}', 'true')).lower() == 'true' for i in range(1, 10)]
    cyl_all_ok = all(cyl_statuses)
    cyl_ok_count = sum(1 for s in cyl_statuses if s)

    low_press_alarm = str(tel.get('low_pressure_alarm', 'false')).lower() == 'true'
    high_press_alarm = str(tel.get('high_pressure_alarm', 'false')).lower() == 'true'

    sys_status_badge = '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">SYSTEM NORMAL</span>' if not (low_press_alarm or high_press_alarm or alarms_count > 0) else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">ALARM TRIGGERED</span>'

    # Build individual panel status rows (for 9 Fire Panels / separations)
    panels_rows = ""
    for i in range(1, 10):
        cyl_key = f"cylinder_pressure_{i}"
        cyl_val = str(tel.get(cyl_key, 'true')).lower() == 'true'
        cyl_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">PRESSURE OK</span>' if cyl_val else '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">PRESSURE LOW</span>'

        di_key = f"di{i}"
        di_val = str(tel.get(di_key, 'true')).lower() == 'true'
        di_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">CLOSED / NORMAL</span>' if di_val else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">OPEN / CHECK</span>'

        panels_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#c62828;">Fire Suppression {i}</td>
            <td style="padding:12px;text-align:center;">{cyl_badge}</td>
            <td style="padding:12px;text-align:center;">{di_badge}</td>
            <td style="padding:12px;">Cylinder {i} Gas Pressure Sensor</td>
            <td style="padding:12px;color:#4caf50;font-weight:bold;">Operational</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily Fire Suppression Safety Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #b71c1c 0%, #c62828 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">🧯 Daily Fire Suppression & Safety Infrastructure Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Overall Status: {sys_status_badge}</p>
            </div>

            <!-- Executive Summary Cards -->
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if relay_online else '#f44336'};">{'ONLINE' if relay_online else 'OFFLINE'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Relay Gateway State</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if low_press_ok and not low_press_alarm else '#f44336'};">{'NORMAL' if low_press_ok else 'LOW'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Low Pressure Line</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if high_press_ok and not high_press_alarm else '#f44336'};">{'NORMAL' if high_press_ok else 'HIGH ALARM'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">High Pressure Line</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if cyl_all_ok else '#f44336'};">{f'{cyl_ok_count} / 9 OK' if cyl_all_ok else f'{cyl_ok_count} / 9 FAULT'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Cylinders Pressure</div>
                </div>
            </div>

            <!-- Breakdown Table -->
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 Fire Panels & Cylinder Safety Status</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #ffebee; text-align: left; border-bottom: 2px solid #ffcdd2;">
                            <th style="padding: 10px;">Panel Zone</th>
                            <th style="padding: 10px; text-align:center;">Cylinder Pressure</th>
                            <th style="padding: 10px; text-align:center;">Digital Input (DI)</th>
                            <th style="padding: 10px;">Sensor Type</th>
                            <th style="padding: 10px;">Health State</th>
                        </tr>
                    </thead>
                    <tbody>
                        {panels_rows}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated Fire Suppression Safety Report • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ==============================================================================
# REPORT 4: FIRE SUPPRESSION UPS ROOM 2 REPORT GENERATOR
# ==============================================================================
def generate_fire_suppression_ups_room_2_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    fire_dev = next((d for d in devices_summary if "UPS Room 2" in d['name']), None)

    tel = fire_dev['telemetry'] if fire_dev else {}
    alarms_count = fire_dev['alarms_count'] if fire_dev else 0
    is_active = fire_dev['is_active'] if fire_dev else False

    # Check 10 cylinders/panels in UPS Room 2
    # 1 / '1' = High Pressure (Normal), 0 / '0' = Low Pressure (Fault)
    cyl_statuses = []
    for i in range(1, 11):
        k = f"fire_suppression_{i}_pressure"
        val = tel.get(k)
        if val is None:
            cyl_statuses.append(None)
        else:
            cyl_statuses.append(str(val).lower() in ('1', 'true'))

    cyl_reported = [s for s in cyl_statuses if s is not None]
    cyl_ok_count = sum(1 for s in cyl_reported if s)
    total_panels = 10
    has_fault = any(s is False for s in cyl_statuses)

    sys_status_badge = (
        '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">ALL CYLINDERS NORMAL</span>'
        if (not has_fault and alarms_count == 0 and len(cyl_reported) > 0)
        else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">LOW PRESSURE DETECTED</span>'
    )

    panels_rows = ""
    for i in range(1, 11):
        cyl = cyl_statuses[i - 1]
        if cyl is None:
            cyl_badge = '<span style="background-color:#9e9e9e;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">NO DATA</span>'
            status_text = '<span style="color:#757575;">No reading</span>'
        elif cyl:
            cyl_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">HIGH PRESSURE (OK)</span>'
            status_text = '<span style="color:#2e7d32;font-weight:bold;">Normal</span>'
        else:
            cyl_badge = '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">LOW PRESSURE</span>'
            status_text = '<span style="color:#c62828;font-weight:bold;">Attention Required</span>'

        panels_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#c62828;">Fire Suppression {i}</td>
            <td style="padding:12px;">UPS Room 2 &mdash; Gas Cylinder {i}</td>
            <td style="padding:12px;text-align:center;">{cyl_badge}</td>
            <td style="padding:12px;">Pressure Switch Sensor</td>
            <td style="padding:12px;">{status_text}</td>
        </tr>
        """

    active_badge = (
        '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:bold;">ONLINE</span>'
        if is_active
        else '<span style="background-color:#757575;color:#fff;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:bold;">STANDBY</span>'
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily Fire Suppression UPS Room 2 Safety Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #b71c1c 0%, #c62828 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">🧯 Daily Fire Suppression Safety Report &mdash; UPS Room 2</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Overall Status: {sys_status_badge}</p>
            </div>

            <!-- Executive Summary Cards -->
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if is_active else '#757575'};">{active_badge}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Zone Gateway Status</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: #1565c0;">10 Panels</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Monitored Cylinders</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if cyl_ok_count == total_panels else '#ef6c00'};">{cyl_ok_count} / {total_panels} OK</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Normal Pressure</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if alarms_count == 0 else '#f44336'};">{alarms_count} Active</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Safety Alarms</div>
                </div>
            </div>

            <!-- Breakdown Table -->
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 UPS Room 2 &mdash; 10 Fire Panel Zones &amp; Cylinder Pressures</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #ffebee; text-align: left; border-bottom: 2px solid #ffcdd2;">
                            <th style="padding: 10px;">Panel Zone</th>
                            <th style="padding: 10px;">Location / Description</th>
                            <th style="padding: 10px; text-align:center;">Cylinder Pressure</th>
                            <th style="padding: 10px;">Sensor Type</th>
                            <th style="padding: 10px;">Health State</th>
                        </tr>
                    </thead>
                    <tbody>
                        {panels_rows}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated Fire Suppression Safety Report &bull; Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """
    return html

# ==============================================================================
# EMAIL SENDER FOR SEPARATE REPORTS
# ==============================================================================
def send_single_report_email(subject, html_content, recipients_override=None):
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
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"ThingsBoard Safety Monitor <{sender_from}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(html_content, "html"))

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
        print(f"✅ Report Sent: '{subject}' to {len(recipients)} recipient(s).")
        return True
    except Exception as e:
        print(f"❌ Failed sending '{subject}': {e}")
        return False

def generate_all_separate_reports(summary=None):
    if not summary:
        summary = fetch_master_devices_summary()

    dg_html = generate_dg_set_report(summary)
    lt_html = generate_lt_panels_report(summary)
    fire_html = generate_fire_suppression_report(summary)
    fire_ups2_html = generate_fire_suppression_ups_room_2_report(summary)

    date_str = datetime.now().strftime('%d %b %Y')

    return {
        "dg_set": {
            "subject": f"⚡ Daily DG Set Operations Report — {date_str}",
            "html": dg_html
        },
        "lt_panels": {
            "subject": f"🔌 Daily LT Panels Electrical Report — {date_str}",
            "html": lt_html
        },
        "fire_suppression": {
            "subject": f"🧯 Daily Fire Suppression Safety Report — {date_str}",
            "html": fire_html
        },
        "fire_ups_room2": {
            "subject": f"🧯 Daily Fire Suppression UPS Room 2 Safety Report — {date_str}",
            "html": fire_ups2_html
        }
    }

def main():
    args = sys.argv[1:]
    
    print("Fetching master devices summary from ThingsBoard...")
    summary = fetch_master_devices_summary()
    reports = generate_all_separate_reports(summary)

    if "--preview" in args:
        p1 = "/home/ubuntu/thingsboard/dg_set_report_preview.html"
        p2 = "/home/ubuntu/thingsboard/lt_panels_report_preview.html"
        p3 = "/home/ubuntu/thingsboard/fire_suppression_report_preview.html"
        p4 = "/home/ubuntu/thingsboard/fire_suppression_ups_room2_report_preview.html"

        with open(p1, "w", encoding="utf-8") as f: f.write(reports["dg_set"]["html"])
        with open(p2, "w", encoding="utf-8") as f: f.write(reports["lt_panels"]["html"])
        with open(p3, "w", encoding="utf-8") as f: f.write(reports["fire_suppression"]["html"])
        with open(p4, "w", encoding="utf-8") as f: f.write(reports["fire_ups_room2"]["html"])

        print(f"✅ HTML Previews saved:")
        print(f"   1. DG Set: {p1}")
        print(f"   2. LT Panels: {p2}")
        print(f"   3. Fire Suppression: {p3}")
        print(f"   4. Fire Suppression UPS Room 2: {p4}")

    if "--send-now" in args:
        recipients = None
        for a in args:
            if a.startswith("--to="):
                recipients = a.split("=")[1]
        
        print("\nSending 4 separate email reports...")
        send_single_report_email(reports["dg_set"]["subject"], reports["dg_set"]["html"], recipients)
        send_single_report_email(reports["lt_panels"]["subject"], reports["lt_panels"]["html"], recipients)
        send_single_report_email(reports["fire_suppression"]["subject"], reports["fire_suppression"]["html"], recipients)
        send_single_report_email(reports["fire_ups_room2"]["subject"], reports["fire_ups_room2"]["html"], recipients)
        print("Done!")

    if "--daemon" in args:
        print("=================================================================")
        print("   SEPARATE EMAIL REPORTS DAEMON ACTIVATED (Runs at 08:00 AM IST)")
        print("=================================================================")
        while True:
            # Check for 08:00 AM IST (which is 02:30 AM UTC)
            now_utc = datetime.utcnow()
            # 02:30 UTC = 08:00 AM IST
            if now_utc.hour == 2 and now_utc.minute == 30:
                print(f"[{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}] Dispatching 4 daily scheduled separate reports...")
                summary = fetch_master_devices_summary()
                reports = generate_all_separate_reports(summary)
                send_single_report_email(reports["dg_set"]["subject"], reports["dg_set"]["html"])
                send_single_report_email(reports["lt_panels"]["subject"], reports["lt_panels"]["html"])
                send_single_report_email(reports["fire_suppression"]["subject"], reports["fire_suppression"]["html"])
                send_single_report_email(reports["fire_ups_room2"]["subject"], reports["fire_ups_room2"]["html"])
                time.sleep(60)
            time.sleep(30)

    if not args:
        print("\nUsage:")
        print("  python3 generate_separate_reports.py --preview              (Generates HTML preview files for all 4 reports)")
        print("  python3 generate_separate_reports.py --send-now             (Sends all 4 separate email reports immediately)")
        print("  python3 generate_separate_reports.py --send-now --to=a@b.com (Sends 4 separate reports to specific email)")
        print("  python3 generate_separate_reports.py --daemon               (Runs background scheduler daily at 08:00 AM IST)")

if __name__ == "__main__":
    main()
