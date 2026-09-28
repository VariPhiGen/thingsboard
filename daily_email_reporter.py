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

BASE_URL = os.getenv("TB_BASE_URL", "http://localhost:9091")
SYSADMIN_USER = os.getenv("TB_USER", "sysadmin@thingsboard.org")
SYSADMIN_PASS = os.getenv("TB_PASS", "sysadmin")

# Email SMTP Settings
SMTP_SERVER = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "smtpout.secureserver.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER", "information@variphi.com")
SMTP_PASSWORD = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER
REPORT_RECIPIENTS = os.getenv("REPORT_RECIPIENTS", "shivamskr151@gmail.com")

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def get_tenant_headers():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    ten_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    user_id = requests.get(f"{BASE_URL}/api/tenant/{ten_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{user_id}/token", headers=sys_headers).json()['token']
    return {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

def fetch_master_devices_summary():
    headers = get_tenant_headers()
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=headers).json()['data']
    
    summary = []
    now_ts = int(time.time() * 1000)
    start_24h_ts = now_ts - (24 * 3600 * 1000)

    for dev in devices:
        dev_id = dev['id']['id']
        name = dev['name']
        dev_type = dev.get('type', 'DEFAULT')

        # Attributes
        attrs_res = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/values/attributes", headers=headers)
        attrs = attrs_res.json() if attrs_res.ok else []
        attr_dict = {a['key']: a['value'] for a in attrs}
        
        is_active = attr_dict.get('active', False)
        last_act = attr_dict.get('lastActivityTime', 0)
        last_act_str = datetime.fromtimestamp(last_act/1000).strftime('%Y-%m-%d %H:%M:%S') if last_act else "No activity"

        # Latest Telemetry Keys
        keys_res = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/keys/timeseries", headers=headers)
        keys = keys_res.json() if keys_res.ok else []
        
        tel_data = {}
        agg_24h = {}

        if keys:
            k_str = ",".join(keys)
            vals_res = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}", headers=headers)
            if vals_res.ok:
                raw_vals = vals_res.json()
                for k, v in raw_vals.items():
                    if v:
                        tel_data[k] = v[0]['value']

            # 24-Hour Aggregations (AVG, MAX, MIN)
            try:
                avg_res = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={start_24h_ts}&endTs={now_ts}&interval=86400000&agg=AVG", headers=headers)
                if avg_res.ok:
                    for k, v in avg_res.json().items():
                        if v and v[0].get('value') is not None:
                            try: agg_24h[f"{k}_24h_avg"] = round(float(v[0]['value']), 1)
                            except: pass

                max_res = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={start_24h_ts}&endTs={now_ts}&interval=86400000&agg=MAX", headers=headers)
                if max_res.ok:
                    for k, v in max_res.json().items():
                        if v and v[0].get('value') is not None:
                            try: agg_24h[f"{k}_24h_max"] = round(float(v[0]['value']), 1)
                            except: pass
            except Exception as e:
                print(f"Aggregation error for {name}: {e}")

        # Alarms
        alarms_res = requests.get(f"{BASE_URL}/api/alarm/DEVICE/{dev_id}?pageSize=50&page=0&status=ACTIVE_UNACK,ACTIVE_ACK", headers=headers)
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

def generate_html_report(devices_summary):
    date_str = datetime.now().strftime('%d %B %Y')
    time_str = datetime.now().strftime('%H:%M:%S IST')

    total_devices = len(devices_summary)
    active_count = sum(1 for d in devices_summary if d['is_active'])
    inactive_count = total_devices - active_count
    total_alarms = sum(d['alarms_count'] for d in devices_summary)

    rows_html = ""
    for d in devices_summary:
        status_badge = f'<span style="background-color:#4caf50;color:#fff;padding:4px 8px;border-radius:12px;font-size:12px;font-weight:bold;">ACTIVE</span>' if d['is_active'] else f'<span style="background-color:#f44336;color:#fff;padding:4px 8px;border-radius:12px;font-size:12px;font-weight:bold;">INACTIVE</span>'
        
        tel = d['telemetry']
        agg = d['agg_24h']
        
        kpi_list = []
        
        # 1. DG Sets KPIs
        if 'power_kw' in tel or 'power_kw_24h_avg' in agg:
            pwr_curr = f"{tel.get('power_kw', 'N/A')} kW"
            pwr_avg = f"{agg.get('power_kw_24h_avg', 'N/A')} kW"
            pwr_max = f"{agg.get('power_kw_24h_max', 'N/A')} kW"
            kpi_list.append(f"⚡ <b>Power:</b> {pwr_curr} (24h Avg: {pwr_avg}, Max: {pwr_max})")

        if 'energy_kwh' in tel:
            kpi_list.append(f"🔋 <b>Total Energy:</b> {tel['energy_kwh']} kWh")

        if 'run_hours' in tel:
            kpi_list.append(f"⏱️ <b>Run Hours:</b> {tel['run_hours']} h")

        if 'fuel_level' in tel or 'fuel_level_24h_avg' in agg:
            fuel_curr = f"{tel.get('fuel_level', 'N/A')}%"
            fuel_avg = f"{agg.get('fuel_level_24h_avg', 'N/A')}%"
            kpi_list.append(f"⛽ <b>Fuel Level:</b> {fuel_curr} (24h Avg: {fuel_avg})")

        # 2. RO Plant System KPIs
        if 'tds' in tel or 'tds_24h_avg' in agg:
            tds_curr = f"{tel.get('tds', 'N/A')} ppm"
            tds_avg = f"{agg.get('tds_24h_avg', 'N/A')} ppm"
            tds_max = f"{agg.get('tds_24h_max', 'N/A')} ppm"
            kpi_list.append(f"💧 <b>TDS Level:</b> {tds_curr} (24h Avg: {tds_avg}, Max: {tds_max})")

        if 'water_flow' in tel or 'water_flow_24h_avg' in agg:
            flow_curr = f"{tel.get('water_flow', 'N/A')} L/min"
            flow_avg = f"{agg.get('water_flow_24h_avg', 'N/A')} L/min"
            kpi_list.append(f"🌊 <b>Permeate Flow:</b> {flow_curr} (24h Avg: {flow_avg})")

        if 'pressure' in tel or 'pressure_24h_avg' in agg:
            press_curr = f"{tel.get('pressure', 'N/A')} psi"
            press_avg = f"{agg.get('pressure_24h_avg', 'N/A')} psi"
            kpi_list.append(f"⚙️ <b>RO Pressure:</b> {press_curr} (24h Avg: {press_avg})")

        if 'status' in tel:
            kpi_list.append(f"📊 <b>Status:</b> {tel['status']}")

        metrics_str = "<br/>".join(kpi_list) if kpi_list else "<i style='color:#888;'>No 24h telemetry recorded</i>"
        alarms_str = f'<b style="color:#f44336;">{d["alarms_count"]} Active Alerts</b>' if d['alarms_count'] > 0 else '<span style="color:#4caf50;">Normal</span>'

        rows_html += f"""
        <tr style="border-bottom: 1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#1a237e;">{d['name']}</td>
            <td style="padding:12px;">{d['type']}</td>
            <td style="padding:12px;text-align:center;">{status_badge}</td>
            <td style="padding:12px;line-height:1.5;">{metrics_str}</td>
            <td style="padding:12px;text-align:center;">{alarms_str}</td>
            <td style="padding:12px;color:#757575;font-size:12px;">{d['last_activity']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily System Health & Telemetry Summary Report</title>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px;">
        <div style="max-width: 900px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: #ffffff; padding: 25px 30px;">
                <h1 style="margin: 0; font-size: 24px; letter-spacing: 0.5px;">🏢 Virtuoso NetSoft — Daily Master Devices Report</h1>
                <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">Date: {date_str} | Generated At: {time_str}</p>
            </div>

            <!-- Executive Summary Cards -->
            <div style="display: flex; padding: 20px; background: #fafafa; border-bottom: 1px solid #eeeeee;">
                <div style="flex: 1; text-align: center; padding: 10px; background: #ffffff; margin: 5px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #1e3c72;">{total_devices}</div>
                    <div style="font-size: 12px; color: #666; text-transform: uppercase;">Total Master Devices</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 10px; background: #ffffff; margin: 5px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #4caf50;">{active_count}</div>
                    <div style="font-size: 12px; color: #666; text-transform: uppercase;">Active Devices</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 10px; background: #ffffff; margin: 5px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: #ff9800;">{inactive_count}</div>
                    <div style="font-size: 12px; color: #666; text-transform: uppercase;">Inactive / Offline</div>
                </div>
                <div style="flex: 1; text-align: center; padding: 10px; background: #ffffff; margin: 5px; border-radius: 6px; border: 1px solid #e0e0e0;">
                    <div style="font-size: 26px; font-weight: bold; color: {'#f44336' if total_alarms > 0 else '#4caf50'};">{total_alarms}</div>
                    <div style="font-size: 12px; color: #666; text-transform: uppercase;">Total Active Alarms</div>
                </div>
            </div>

            <!-- Devices Table -->
            <div style="padding: 20px;">
                <h3 style="color: #333; margin-top: 0;">📊 Master Device Live Status Breakdown</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f0f4f8; text-align: left; border-bottom: 2px solid #d0dbe5;">
                            <th style="padding: 10px;">Device Name</th>
                            <th style="padding: 10px;">Profile</th>
                            <th style="padding: 10px; text-align:center;">State</th>
                            <th style="padding: 10px;">Latest Telemetry Highlights</th>
                            <th style="padding: 10px; text-align:center;">Alarms</th>
                            <th style="padding: 10px;">Last Activity</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="background: #f0f4f8; padding: 15px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #e0e0e0;">
                Automated Daily Infrastructure Status Report • ThingsBoard IoT Operations • Virtuoso NetSoft
            </div>
        </div>
    </body>
    </html>
    """
    return html_content

def send_email_report(html_content, recipients_override=None):
    recipients_str = recipients_override or REPORT_RECIPIENTS
    if not recipients_str:
        print("⚠️ No recipients defined! Please set REPORT_RECIPIENTS in .env or pass as argument.")
        return False

    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        print("⚠️ Recipients list is empty.")
        return False

    if not SMTP_USER or not SMTP_PASSWORD:
        print("⚠️ SMTP credentials missing! Set SMTP_USER and SMTP_PASSWORD in .env file.")
        return False

    sender_from = SMTP_FROM or SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Daily Infrastructure Report — {datetime.now().strftime('%d %b %Y')}"
    msg["From"] = f"ThingsBoard IoT Monitor <{sender_from}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(html_content, "html"))

    try:
        print(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20)
            server.ehlo()
            server.starttls()
            
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(sender_from, recipients, msg.as_string())
        server.quit()
        print(f"✅ Daily Email Report successfully sent to {len(recipients)} recipient(s): {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email report: {e}")
        return False

def main():
    args = sys.argv[1:]
    
    print("Fetching master devices summary from ThingsBoard...")
    summary = fetch_master_devices_summary()
    html_report = generate_html_report(summary)

    if "--preview" in args:
        preview_path = "/home/ubuntu/thingsboard/daily_report_preview.html"
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_report)
        print(f"✅ HTML Daily Report Preview saved to: {preview_path}")

    if "--send-now" in args:
        recipients = None
        for a in args:
            if a.startswith("--to="):
                recipients = a.split("=")[1]
        send_email_report(html_report, recipients)

    if "--daemon" in args:
        print("=======================================================")
        print("   DAILY EMAIL REPORT DAEMON ACTIVATED (Runs at 08:00) ")
        print("=======================================================")
        while True:
            now = datetime.now()
            # Check if current time is 08:00 AM
            if now.hour == 8 and now.minute == 0:
                print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Triggering scheduled Daily Email Report...")
                summary = fetch_master_devices_summary()
                html_report = generate_html_report(summary)
                send_email_report(html_report)
                time.sleep(60) # Prevent multiple sends in same minute
            time.sleep(30)

    if not args:
        print("\nUsage:")
        print("  python3 daily_email_reporter.py --preview              (Generates HTML preview file)")
        print("  python3 daily_email_reporter.py --send-now             (Sends email report immediately)")
        print("  python3 daily_email_reporter.py --send-now --to=a@b.com (Sends report to specific email)")
        print("  python3 daily_email_reporter.py --daemon               (Runs background scheduler at 08:00 AM)")

if __name__ == "__main__":
    main()
