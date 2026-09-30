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
from email.mime.application import MIMEApplication

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
# PDF GENERATOR CLIENT FUNCTION
# ==============================================================================
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

def convert_html_to_pdf(html_content, filename_hint="report.pdf"):
    try:
        base = get_pdf_generator_url()
        url = f"{base}/render-raw-html-pdf"
        res = requests.post(url, json={"html": html_content}, timeout=60)
        if res.status_code == 200:
            return res.content
        print(f"⚠️ PDF generator ({url}) status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"⚠️ PDF generation error for {filename_hint}: {e}")
    return None

# ==============================================================================
# 1. SEPARATE DG SET 24H REPORT HTML
# ==============================================================================
def generate_dg_set_html(devices_summary):
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
        status_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">ACTIVE</span>' if d['is_active'] else '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">OFFLINE</span>'
        tel = d['telemetry']
        agg = d['agg_24h']
        
        coolant = tel.get('coolant_temp', 'N/A')
        coolant_disp = f"{coolant} °C" if coolant != '32767' and coolant != 'N/A' else "Sensor Offline"
        oil_p = tel.get('oil_pressure', 'N/A')
        oil_p_disp = f"{oil_p} bar" if oil_p != '32767' and oil_p != 'N/A' else "Sensor Offline"

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

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#0d47a1;">{d['name']}<br/>{status_badge}</td>
            <td style="padding:12px;text-align:center;">{dg_state_badge}</td>
            <td style="padding:12px;line-height:1.6;">
                ⚡ <b>Live Power:</b> {pwr} (24h Max: {pwr_max})<br/>
                🔋 <b>Cumulative Energy:</b> {energy}<br/>
                ⏱️ <b>Run Hours:</b> {run_h} | 🔄 <b>Starts:</b> {starts}
            </td>
            <td style="padding:12px;line-height:1.6;">
                ⛽ <b>Fuel Level:</b> {fuel}<br/>
                📊 <b>24h Avg Fuel:</b> {fuel_avg} (Min: {fuel_min})<br/>
                🔋 <b>Battery Voltage:</b> {bat_v}
            </td>
            <td style="padding:12px;line-height:1.6;">
                🌡️ <b>Coolant Temp:</b> {coolant_disp}<br/>
                ⚙️ <b>Oil Pressure:</b> {oil_p_disp}
            </td>
            <td style="padding:12px;color:#757575;font-size:11px;">{d['last_activity']}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily 24-Hour DG Sets Operations Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #0d47a1 0%, #1976d2 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px;">⚡ Daily 24-Hour Diesel Generator (DG Set) Operations Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str}</p>
            </div>
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
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">24h Energy Generated</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: {'#f44336' if total_alarms > 0 else '#4caf50'};">{total_alarms}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Active Alarms</div>
                </div>
            </div>
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 DG Sets Detailed 24h Operational Breakdown</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #e3f2fd; text-align: left; border-bottom: 2px solid #bbdefb;">
                            <th style="padding: 10px;">DG Set Name</th>
                            <th style="padding: 10px; text-align:center;">State</th>
                            <th style="padding: 10px;">Power & 24h Energy</th>
                            <th style="padding: 10px;">Fuel Level & Battery</th>
                            <th style="padding: 10px;">Engine Health</th>
                            <th style="padding: 10px;">Last Sync</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated DG Set 24h Operations PDF Report • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """

# ==============================================================================
# 2. SEPARATE LT PANELS 24H REPORT HTML
# ==============================================================================
def generate_lt_panels_html(devices_summary):
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
    active_panels = sum(1 for _, prefix in panels_def if safe_float(tel.get(f"{prefix}_voltage")) > 0)
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
        panel_status = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">LIVE ENERGIZED</span>' if has_data else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:bold;">STANDBY</span>'

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#2e7d32;">{name}</td>
            <td style="padding:12px;text-align:center;">{panel_status}</td>
            <td style="padding:12px;font-weight:bold;color:#1b5e20;">{p} kW</td>
            <td style="padding:12px;">{v} V</td>
            <td style="padding:12px;">{i} A</td>
            <td style="padding:12px;">{freq} Hz</td>
            <td style="padding:12px;line-height:1.5;">
                📊 <b>24h Avg Power:</b> {p_avg} kW<br/>
                ⚡ <b>24h Max Power:</b> {p_max} kW (Max V: {v_max} V)
            </td>
        </tr>
        """

    master_badge = '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">MASTER ONLINE</span>' if is_active else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">MASTER OFFLINE</span>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily 24-Hour LT Panels Electrical Load Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #1b5e20 0%, #388e3c 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px;">🔌 Daily 24-Hour Low Voltage (LT) Panels Electrical Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Status: {master_badge}</p>
            </div>
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
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 LT Sub-Panels Electrical 24h Aggregations</h3>
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
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated LT Panels 24h Electrical PDF Report • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """

# ==============================================================================
# 3. SEPARATE FIRE SUPPRESSION 24H REPORT HTML
# ==============================================================================
def generate_fire_suppression_html(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    fire_dev = next((d for d in devices_summary if "Fire" in d['name'] or d['type'] == 'LT Panel Fire Profile'), None)
    tel = fire_dev['telemetry'] if fire_dev else {}
    alarms_count = fire_dev['alarms_count'] if fire_dev else 0

    relay_online = str(tel.get('relay_online', 'true')).lower() == 'true'
    low_press_ok = str(tel.get('low_pressure', 'true')).lower() == 'true'
    high_press_ok = str(tel.get('high_pressure', 'true')).lower() == 'true'
    cyl1_ok = str(tel.get('cylinder_pressure_1', 'true')).lower() == 'true'
    cyl2_ok = str(tel.get('cylinder_pressure_2', 'true')).lower() == 'true'
    cyl3_ok = str(tel.get('cylinder_pressure_3', 'true')).lower() == 'true'

    sys_status_badge = '<span style="background-color:#4caf50;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">SYSTEM NORMAL</span>' if not (alarms_count > 0) else '<span style="background-color:#f44336;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">ALARM TRIGGERED</span>'

    panels_rows = ""
    for i in range(1, 4):
        cyl_val = str(tel.get(f"cylinder_pressure_{i}", 'true')).lower() == 'true'
        cyl_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">PRESSURE OK</span>' if cyl_val else '<span style="background-color:#f44336;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">PRESSURE LOW</span>'

        di_val = str(tel.get(f"di{i}", 'true')).lower() == 'true'
        di_badge = '<span style="background-color:#4caf50;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">CLOSED / NORMAL</span>' if di_val else '<span style="background-color:#ff9800;color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:bold;">OPEN / CHECK</span>'

        panels_rows += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#c62828;">Fire Separation Panel {i}</td>
            <td style="padding:12px;text-align:center;">{cyl_badge}</td>
            <td style="padding:12px;text-align:center;">{di_badge}</td>
            <td style="padding:12px;">Cylinder {i} Gas Pressure Sensor</td>
            <td style="padding:12px;color:#4caf50;font-weight:bold;">Operational (24h Monitored)</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily 24-Hour Fire Suppression Safety Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #b71c1c 0%, #c62828 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px;">🧯 Daily 24-Hour Fire Suppression Safety Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Overall Status: {sys_status_badge}</p>
            </div>
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if relay_online else '#f44336'};">{'ONLINE' if relay_online else 'OFFLINE'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Relay Gateway State</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if low_press_ok else '#f44336'};">{'NORMAL' if low_press_ok else 'LOW'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Low Pressure Line</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if high_press_ok else '#f44336'};">{'NORMAL' if high_press_ok else 'HIGH ALARM'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">High Pressure Line</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: {'#4caf50' if (cyl1_ok and cyl2_ok and cyl3_ok) else '#f44336'};">{'3 / 3 OK' if (cyl1_ok and cyl2_ok and cyl3_ok) else 'FAULT'}</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Cylinders Pressure</div>
                </div>
            </div>
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
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated Fire Suppression 24h Safety PDF Report • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """

# ==============================================================================
# 4. SEPARATE RO PLANT 24H REPORT HTML
# ==============================================================================
def generate_ro_plant_html(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

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

    ro_badge = f'<span style="background-color:#0288d1;color:#fff;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:bold;">{ro_status}</span>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily 24-Hour RO Plant Water Quality Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #0288d1 0%, #039be5 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px;">💧 Daily 24-Hour RO Plant Water Quality & Treatment Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str} | Status: {ro_badge}</p>
            </div>
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: #0288d1;">{ro_tds} ppm</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Live TDS Level</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: #039be5;">{ro_tds_avg} ppm</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">24h Avg TDS</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: #00897b;">{ro_flow} L/min</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">Permeate Water Flow</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 12px; background: #ffffff; margin: 4px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 24px; font-weight: bold; color: #4caf50;">{ro_press} psi</div>
                    <div style="font-size: 11px; color: #666; text-transform: uppercase;">RO Pressure</div>
                </div>
            </div>
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 Water Quality & 24h Monitoring Metrics</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #e1f5fe; text-align: left; border-bottom: 2px solid #b3e5fc;">
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
                            <td style="padding:10px;color:#4caf50;font-weight:bold;">Optimal (&lt; 200 ppm)</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e0e0e0;">
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">Permeate Water Flow Rate</td>
                            <td style="padding:10px;font-weight:bold;">{ro_flow} L/min</td>
                            <td style="padding:10px;">{ro_flow_avg} L/min</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#4caf50;font-weight:bold;">Normal Flow</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e0e0e0;">
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">RO Membrane Pressure</td>
                            <td style="padding:10px;font-weight:bold;">{ro_press} psi</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#4caf50;font-weight:bold;">Normal Pressure</td>
                        </tr>
                        <tr>
                            <td style="padding:10px;font-weight:bold;color:#0369a1;">pH Level</td>
                            <td style="padding:10px;font-weight:bold;">{ro_ph}</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;">-</td>
                            <td style="padding:10px;color:#4caf50;font-weight:bold;">Balanced (6.5 - 8.5)</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated RO Plant Water Treatment 24h PDF Report • Virtuoso NetSoft Infrastructure Operations
            </div>
        </div>
    </body>
    </html>
    """

# ==============================================================================
# GENERATE ALL 4 SEPARATE PDFS & EMAIL DISPATCH
# ==============================================================================
def generate_all_separate_pdfs(summary=None):
    if not summary:
        summary = fetch_master_devices_summary()

    date_fn = datetime.now().strftime('%Y%m%d')

    reports = [
        {
            "id": "dg_set",
            "name": "DG Set Operations Report",
            "filename": f"DG_Set_24h_Report_{date_fn}.pdf",
            "html": generate_dg_set_html(summary)
        },
        {
            "id": "lt_panels",
            "name": "LT Panels Power Report",
            "filename": f"LT_Panels_24h_Report_{date_fn}.pdf",
            "html": generate_lt_panels_html(summary)
        },
        {
            "id": "fire_suppression",
            "name": "Fire Suppression Safety Report",
            "filename": f"Fire_Suppression_24h_Report_{date_fn}.pdf",
            "html": generate_fire_suppression_html(summary)
        },
        {
            "id": "ro_plant",
            "name": "RO Plant Water Quality Report",
            "filename": f"RO_Plant_24h_Report_{date_fn}.pdf",
            "html": generate_ro_plant_html(summary)
        }
    ]

    for item in reports:
        print(f"Generating PDF for {item['name']} ({item['filename']})...")
        pdf_bytes = convert_html_to_pdf(item['html'], filename_hint=item['filename'])
        item['pdf_bytes'] = pdf_bytes

    return reports

def send_email_with_separate_pdfs(reports, recipients_override=None):
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

    msg["Subject"] = f"📑 Daily 24-Hour Infrastructure PDF Reports — {date_str} (4 PDF Attachments)"
    msg["From"] = f"ThingsBoard Infrastructure Operations <{sender_from}>"
    msg["To"] = ", ".join(recipients)

    intro_html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin:0; padding:20px;">
        <div style="max-width: 800px; margin:0 auto; background:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.1); padding:25px;">
            <h2 style="color: #0f172a; margin-top:0;">🏢 Daily 24-Hour Master Infrastructure Reports</h2>
            <p style="color: #475569; font-size:14px;">Date: <b>{date_str}</b></p>
            <p style="color: #334155; font-size:14px;">Please find attached the <b>4 separate PDF reports</b> covering complete 24-hour infrastructure records:</p>
            <ul style="line-height:1.8; color: #1e293b; font-size:14px;">
                <li>⚡ <b>1. DG Set Operations Report PDF</b> (<code>DG_Set_24h_Report.pdf</code>)</li>
                <li>🔌 <b>2. LT Panels Electrical & Load Report PDF</b> (<code>LT_Panels_24h_Report.pdf</code>)</li>
                <li>🧯 <b>3. Fire Suppression Safety Report PDF</b> (<code>Fire_Suppression_24h_Report.pdf</code>)</li>
                <li>💧 <b>4. RO Plant Water Quality Report PDF</b> (<code>RO_Plant_24h_Report.pdf</code>)</li>
            </ul>
            <hr style="border:0; border-top:1px solid #e2e8f0; margin:20px 0;" />
            <p style="font-size:12px; color:#94a3b8; text-align:center;">Automated Infrastructure Operations • Virtuoso NetSoft</p>
        </div>
    </body>
    </html>
    """

    msg_body = MIMEMultipart("alternative")
    msg_body.attach(MIMEText(intro_html, "html"))
    msg.attach(msg_body)

    attached_count = 0
    for r in reports:
        pdf_b = r.get('pdf_bytes')
        fn = r.get('filename', 'report.pdf')
        if pdf_b:
            att = MIMEApplication(pdf_b, _subtype="pdf")
            att.add_header("Content-Disposition", "attachment", filename=fn)
            msg.attach(att)
            attached_count += 1
            print(f"📎 Attached PDF: {fn} ({len(pdf_b)} bytes)")
        else:
            print(f"⚠️ PDF missing for {fn}")

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
        print(f"✅ Email with {attached_count} Separate PDF Attachments successfully sent to {len(recipients)} recipient(s): {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ Failed to send separate PDF email report: {e}")
        return False

def main():
    args = sys.argv[1:]
    
    print("Fetching master devices summary from ThingsBoard...")
    summary = fetch_master_devices_summary()
    reports = generate_all_separate_pdfs(summary)

    if "--preview" in args:
        for r in reports:
            html_p = f"/home/ubuntu/thingsboard/{r['id']}_24h_preview.html"
            pdf_p = f"/home/ubuntu/thingsboard/{r['id']}_24h_preview.pdf"

            with open(html_p, "w", encoding="utf-8") as f:
                f.write(r['html'])

            if r.get('pdf_bytes'):
                with open(pdf_p, "wb") as f:
                    f.write(r['pdf_bytes'])
                print(f"✅ Generated Preview: {pdf_p} ({len(r['pdf_bytes'])} bytes)")

    if "--send-now" in args:
        recipients = None
        for a in args:
            if a.startswith("--to="):
                recipients = a.split("=")[1]
        send_email_with_separate_pdfs(reports, recipients)

    if not args:
        print("\nUsage:")
        print("  python3 generate_separate_pdfs_report.py --preview              (Generates HTML and 4 separate PDF preview files)")
        print("  python3 generate_separate_pdfs_report.py --send-now             (Sends email with 4 separate PDF attachments)")
        print("  python3 generate_separate_pdfs_report.py --send-now --to=a@b.com (Sends report to specific email)")

if __name__ == "__main__":
    main()
