#!/usr/bin/env python3
import requests
import smtplib
import time
import json
import os
import sys
import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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

REPORT_TZ = ZoneInfo("Asia/Kolkata")

def report_window(report_date=None):
    """(start_ms, end_ms) of the report: the last 24h, or the full IST calendar day 'YYYY-MM-DD'."""
    if not report_date:
        end_ts = int(time.time() * 1000)
        return end_ts - 24 * 3600 * 1000, end_ts
    day = datetime.strptime(report_date, "%Y-%m-%d").replace(tzinfo=REPORT_TZ)
    return int(day.timestamp() * 1000), int((day + timedelta(days=1)).timestamp() * 1000)

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

# ==============================================================================
# 24H TIME SERIES (FOR PDF GRAPHS)
# ==============================================================================
CHART_BUCKET_MS = 30 * 60 * 1000
SENSOR_OFFLINE_VALUES = {32767.0, 65535.0}

LT_PANELS = [
    ("EVM Charger", "EVM_Charger"),
    ("Electrical Room 1", "Electrical_room_1"),
    ("UPS Room 1", "UPS_Room_1"),
    ("Transformer 1", "Transformer_1"),
    ("Transformer 2", "Transformer_2"),
    ("Transformer 3", "Transformer_3"),
    ("UPS Panel 2", "UPS_Panel_2"),
    ("Fire Fighting Wall", "Fire_fighting_wall")
]

# Keys whose raw 24h history is fetched for graphs and 24h stats (avg/min/max/delta)
REPORT_KEYS = (
    {"power_kw", "fuel_level", "battery_voltage", "coolant_temp", "oil_pressure", "engine_rpm", "energy_kwh"}
    | {"tds", "water_flow", "pressure", "ph"}
    | {"relay_online"} | {f"cylinder_pressure_{i}" for i in range(1, 10)}
    | {f"{prefix}_{m}" for _, prefix in LT_PANELS for m in ("power", "voltage", "current", "frequency")}
)

def fetch_series_24h(base, headers, dev_id, keys, start_ts, end_ts):
    """Raw 24h telemetry -> (series, stats).
    series: per key, values averaged into CHART_BUCKET_MS buckets. Booleans become 1/0,
    so a bucket value is the share of 'true' samples.
    stats: per key '{k}_24h_avg/min/max/delta' over valid samples (sensor-offline values dropped)."""
    if not keys:
        return {}, {}
    try:
        res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={','.join(keys)}&startTs={start_ts}&endTs={end_ts}&limit=200000", headers=headers, timeout=60)
        if not res.ok:
            return {}, {}
        raw = res.json()
    except Exception as e:
        print(f"Time series fetch error for {dev_id}: {e}")
        return {}, {}

    n = int((end_ts - start_ts) // CHART_BUCKET_MS)
    series, stats = {}, {}
    for k, pts in raw.items():
        sums, counts, valid = [0.0] * n, [0] * n, []
        for p in sorted(pts, key=lambda p: p['ts']):
            v = p.get('value')
            if isinstance(v, bool) or str(v).lower() in ('true', 'false'):
                v = 1.0 if str(v).lower() == 'true' else 0.0
            else:
                try: v = float(v)
                except (ValueError, TypeError): continue
                if v in SENSOR_OFFLINE_VALUES: continue
            valid.append(v)
            i = int((p['ts'] - start_ts) // CHART_BUCKET_MS)
            if 0 <= i < n:
                sums[i] += v
                counts[i] += 1
        series[k] = [sums[i] / counts[i] if counts[i] else None for i in range(n)]
        if valid:
            stats[f"{k}_24h_avg"] = sum(valid) / len(valid)
            stats[f"{k}_24h_min"] = min(valid)
            stats[f"{k}_24h_max"] = max(valid)
            stats[f"{k}_24h_delta"] = valid[-1] - valid[0]
            stats[f"{k}_24h_count"] = len(valid)
    return series, stats

# ==============================================================================
# INLINE SVG CHARTS (static, no JS -> renders in any HTML-to-PDF engine)
# ==============================================================================
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS_COLORS = {"good": "#0ca30c", "serious": "#ec835a", "critical": "#d03b3b", "none": "#e1e0d9"}
INK, INK_2, INK_MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

def _fmt(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}".rstrip('0').rstrip('.') if v != int(v) else f"{v:,.0f}"

def _nice_ticks(lo, hi, count=4):
    if hi == lo:
        pad = abs(hi) * 0.1 or 1
        lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t, end, ticks = math.floor(lo / step) * step, math.ceil(hi / step) * step, []
    while t <= end + step * 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks

def _x_ticks(start_ts, n_buckets, every_hours=3):
    end_ts = start_ts + n_buckets * CHART_BUCKET_MS
    first = datetime.fromtimestamp(start_ts / 1000, REPORT_TZ).replace(minute=0, second=0, microsecond=0)
    ticks, t = [], first.timestamp() * 1000
    while t <= end_ts:
        if t >= start_ts and datetime.fromtimestamp(t / 1000, REPORT_TZ).hour % every_hours == 0:
            ticks.append((t, datetime.fromtimestamp(t / 1000, REPORT_TZ).strftime('%H:%M')))
        t += 3600 * 1000
    return ticks

def _no_data(msg="No valid readings in the report period"):
    return f'<div style="padding:28px;text-align:center;color:{INK_MUTED};font-size:12px;background:#fafafa;border:1px dashed {GRID};border-radius:6px;">{msg}</div>'

def svg_line_chart(series, start_ts, width=900, height=210):
    """series: list of (label, color, values-per-bucket or None)."""
    all_vals = [v for _, _, vals in series for v in vals if v is not None]
    if not all_vals:
        return _no_data()
    n = max(len(vals) for _, _, vals in series)
    ml, mr, mt, mb = 60, 14, 10, 28
    pw, ph = width - ml - mr, height - mt - mb
    yt = _nice_ticks(min(all_vals), max(all_vals))
    y0, y1 = yt[0], yt[-1]
    xs = lambda i: ml + (i + 0.5) / n * pw
    ys = lambda v: mt + ph - (v - y0) / (y1 - y0) * ph

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block;font-family:Arial,sans-serif;">']
    for t in yt:
        y = ys(t)
        parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 6}" y="{y + 4.5:.1f}" text-anchor="end" font-size="13" fill="{INK_MUTED}">{_fmt(t)}</text>')
    parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{mt + ph}" y2="{mt + ph}" stroke="{AXIS}" stroke-width="1"/>')
    for ts, label in _x_ticks(start_ts, n):
        x = ml + (ts - start_ts) / (n * CHART_BUCKET_MS) * pw
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{mt + ph}" y2="{mt + ph + 4}" stroke="{AXIS}"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" font-size="13" fill="{INK_MUTED}">{label}</text>')

    for _, color, vals in series:
        d, pen_down = [], False
        for i, v in enumerate(vals):
            if v is None:
                pen_down = False
                continue
            d.append(f"{'L' if pen_down else 'M'}{xs(i):.1f},{ys(v):.1f}")
            # A lone point between gaps would be invisible as a path, so mark it
            isolated = (i == 0 or vals[i - 1] is None) and (i == len(vals) - 1 or vals[i + 1] is None)
            if isolated:
                parts.append(f'<circle cx="{xs(i):.1f}" cy="{ys(v):.1f}" r="3" fill="{color}"/>')
            pen_down = True
        if d:
            parts.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</svg>')
    return "".join(parts)

def _series_stats(vals, unit):
    vs = [v for v in vals if v is not None]
    if not vs:
        return "no data"
    return f"avg {_fmt(sum(vs) / len(vs))} · min {_fmt(min(vs))} · max {_fmt(max(vs))} {unit}"

def chart_card(title, unit, series, start_ts, width=900, height=210):
    legend = ""
    for label, color, vals in series:
        swatch = f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{color};margin-right:5px;vertical-align:-1px;"></span>' if len(series) > 1 else ""
        name = f'<b style="color:{INK};">{label}</b> ' if len(series) > 1 else ""
        legend += f'<span style="margin-right:16px;white-space:nowrap;">{swatch}{name}{_series_stats(vals, unit)}</span>'
    return f"""
    <div style="page-break-inside:avoid;break-inside:avoid;border:1px solid #e0e0e0;border-radius:6px;padding:12px 14px 8px;margin-bottom:14px;background:#fcfcfb;">
        <div style="font-size:13px;font-weight:bold;color:{INK};">{title} <span style="font-weight:normal;color:{INK_MUTED};">({unit} · 30-min average)</span></div>
        <div style="font-size:11px;color:{INK_2};margin:6px 0 8px;line-height:1.7;">{legend}</div>
        {svg_line_chart(series, start_ts, width, height)}
    </div>
    """

def svg_status_strip(rows, start_ts, width=900):
    """rows: list of (label, values) where each value is the share of OK samples in the bucket (0..1) or None."""
    n = max((len(vals) for _, vals in rows), default=0)
    if not n or all(v is None for _, vals in rows for v in vals):
        return _no_data()
    ml, mr, row_h, gap, mb = 170, 14, 20, 2, 28
    pw = width - ml - mr
    cw = pw / n
    height = len(rows) * (row_h + gap) + mb
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block;font-family:Arial,sans-serif;">']
    for r, (label, vals) in enumerate(rows):
        y = r * (row_h + gap)
        parts.append(f'<text x="{ml - 8}" y="{y + row_h - 5}" text-anchor="end" font-size="13" fill="{INK_2}">{label}</text>')
        for i in range(n):
            v = vals[i] if i < len(vals) else None
            state = "none" if v is None else "good" if v >= 0.999 else "critical" if v <= 0.001 else "serious"
            parts.append(f'<rect x="{ml + i * cw:.1f}" y="{y}" width="{max(cw - gap, 1):.1f}" height="{row_h}" rx="2" fill="{STATUS_COLORS[state]}"/>')
    base_y = len(rows) * (row_h + gap)
    for ts, label in _x_ticks(start_ts, n):
        x = ml + (ts - start_ts) / (n * CHART_BUCKET_MS) * pw
        parts.append(f'<text x="{x:.1f}" y="{base_y + 18}" text-anchor="middle" font-size="13" fill="{INK_MUTED}">{label}</text>')
    parts.append('</svg>')
    legend = "".join(
        f'<span style="margin-right:16px;white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{STATUS_COLORS[k]};margin-right:5px;vertical-align:-1px;"></span>{icon} {text}</span>'
        for k, icon, text in [("good", "✔", "OK for full 30 min"), ("serious", "⚠", "Intermittent fault"), ("critical", "✖", "Fault for full 30 min"), ("none", "–", "No data")]
    )
    return f'<div style="font-size:11px;color:{INK_2};margin:6px 0 10px;">{legend}</div>' + "".join(parts)

def get_tenant_headers():
    base = get_base_url()
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    ten_id = requests.get(f"{base}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    user_id = requests.get(f"{base}/api/tenant/{ten_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{base}/api/user/{user_id}/token", headers=sys_headers).json()['token']
    return {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

def fetch_master_devices_summary(report_date=None):
    """report_date 'YYYY-MM-DD' builds the report for that IST day; None = last 24 hours."""
    base = get_base_url()
    headers = get_tenant_headers()
    devices = requests.get(f"{base}/api/tenant/devices?pageSize=100&page=0", headers=headers).json()['data']
    
    summary = []
    start_24h_ts, now_ts = report_window(report_date)

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
        last_act_str = datetime.fromtimestamp(last_act/1000, REPORT_TZ).strftime('%Y-%m-%d %H:%M:%S') if last_act else "No activity"

        # Latest Telemetry Keys
        keys_res = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/keys/timeseries", headers=headers)
        keys = keys_res.json() if keys_res.ok else []
        
        tel_data = {}
        tel_ts = {}
        agg_24h = {}

        if keys:
            k_str = ",".join(keys)
            if report_date:
                # Latest value of each key as it stood at the end of the report day
                vals_url = f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}&startTs={now_ts - 365 * 86400000}&endTs={now_ts}&limit=1"
            else:
                vals_url = f"{base}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries?keys={k_str}"
            vals_res = requests.get(vals_url, headers=headers)
            if vals_res.ok:
                raw_vals = vals_res.json()
                for k, v in raw_vals.items():
                    if v:
                        tel_data[k] = v[0]['value']
                        tel_ts[k] = v[0]['ts']

            # 24h history: graphs + stats computed locally, because ThingsBoard's server-side
            # AVG/MAX/MIN include sensor-offline values (32767) and return 0 for booleans
            series_24h, agg_24h = fetch_series_24h(base, headers, dev_id, [k for k in keys if k in REPORT_KEYS], start_24h_ts, now_ts)
        else:
            series_24h = {}

        if report_date:
            # Current 'active' attribute says nothing about a past day: online = sent data that day
            fresh_ts = [ts for ts in tel_ts.values() if start_24h_ts <= ts < now_ts]
            is_active = bool(fresh_ts)
            last_ts = max(tel_ts.values(), default=0)
            last_act_str = datetime.fromtimestamp(last_ts / 1000, REPORT_TZ).strftime('%Y-%m-%d %H:%M:%S') if last_ts else "No activity"

        # Alarms (live: currently active; past day: raised during that day)
        if report_date:
            alarms_url = f"{base}/api/alarm/DEVICE/{dev_id}?pageSize=100&page=0&startTime={start_24h_ts}&endTime={now_ts}"
        else:
            alarms_url = f"{base}/api/alarm/DEVICE/{dev_id}?pageSize=50&page=0&status=ACTIVE_UNACK,ACTIVE_ACK"
        alarms_res = requests.get(alarms_url, headers=headers)
        alarms_json = alarms_res.json() if alarms_res.ok else {}
        active_alarms = alarms_json.get('data', [])
        alarms_total = alarms_json.get('totalElements', len(active_alarms))

        summary.append({
            "id": dev_id,
            "name": name,
            "type": dev_type,
            "is_active": is_active,
            "last_activity": last_act_str,
            "telemetry": tel_data,
            "telemetry_ts": tel_ts,
            "agg_24h": agg_24h,
            "alarms_count": alarms_total,
            "active_alarms": [a.get('type') for a in active_alarms],
            "series_start_ts": start_24h_ts,
            "series_end_ts": now_ts,
            "historical": bool(report_date),
            "series_24h": series_24h
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
# SHARED PDF LAYOUT HELPERS
# (no emoji in PDF HTML: the PDF renderer has no emoji font and draws empty boxes)
# ==============================================================================
BADGE_COLORS = {
    "green": "#2e7d32", "red": "#c62828", "amber": "#ef6c00",
    "grey": "#757575", "teal": "#00796b", "blue": "#0277bd",
}

REPORT_CSS = """
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 16px; background: #ffffff; color: #1f2937;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.report { max-width: 960px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.hdr { color: #ffffff; padding: 22px 28px; }
.hdr h1 { margin: 0; font-size: 22px; line-height: 1.3; }
.hdr .meta { margin-top: 8px; font-size: 13px; line-height: 1.8; opacity: 0.95; }
.kpis { display: flex; gap: 10px; padding: 18px 20px; background: #fafafa; border-bottom: 1px solid #eeeeee; }
.kpi { flex: 1; text-align: center; padding: 12px 8px; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; }
.kpi .v { font-size: 22px; font-weight: bold; white-space: nowrap; }
.kpi .l { font-size: 10.5px; color: #666666; text-transform: uppercase; letter-spacing: 0.3px; margin-top: 4px; line-height: 1.3; }
.section { padding: 18px 20px 6px; }
.section h3 { margin: 0 0 12px; font-size: 16px; color: #1f2937; }
.section h3 .sub { font-size: 12px; font-weight: normal; color: #6b7280; }
table.data { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
table.data th { text-align: left; padding: 9px 8px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; color: #374151; }
table.data td { padding: 10px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: middle; overflow-wrap: break-word; }
table.data tr { page-break-inside: avoid; break-inside: avoid; }
table.data .c { text-align: center; }
table.data .r { text-align: right; }
.nw { white-space: nowrap; }
.name { font-weight: bold; }
.badge { display: inline-block; white-space: nowrap; padding: 3px 9px; border-radius: 10px; font-size: 10px; font-weight: bold;
         color: #ffffff; letter-spacing: 0.3px; line-height: 1.4; }
.na { color: #9ca3af; font-weight: normal; }
.kv { line-height: 1.6; margin-bottom: 2px; }
.kv .k { color: #6b7280; }
.muted { color: #6b7280; font-size: 11px; }
.footer { background: #f0f4f8; padding: 14px; text-align: center; font-size: 11.5px; color: #777777; border-top: 1px solid #e0e0e0; }
"""

def fmt_val(val, unit="", decimals=1):
    """Format a telemetry value for display; missing/invalid values never get a unit."""
    if val is None or str(val).strip() in ("", "N/A", "--"):
        return '<span class="na">N/A</span>'
    try:
        f = float(val)
    except (ValueError, TypeError):
        text = str(val).strip()
        return '<span class="na">Sensor Error</span>' if text.lower() == "error" else f'<span class="na">{text}</span>'
    if f in SENSOR_OFFLINE_VALUES:
        return '<span class="na">Sensor Offline</span>'
    return f'<span class="nw">{f:,.{decimals}f}{" " + unit if unit else ""}</span>'

def is_fresh(dev, key):
    """True when the device's latest value for key falls inside the 24h report window."""
    ts = (dev or {}).get('telemetry_ts', {}).get(key)
    return ts is not None and ts >= dev['series_start_ts']

def live_val(dev, key):
    """Latest value of key, or None when it is missing or older than the 24h report window."""
    return dev['telemetry'].get(key) if dev and is_fresh(dev, key) else None

def fmt_latest(dev, key, unit="", decimals=1):
    """fmt_val of the latest value; a value older than the report window is greyed and dated."""
    if not dev or key not in dev['telemetry']:
        return fmt_val(None)
    val = fmt_val(dev['telemetry'][key], unit, decimals)
    if is_fresh(dev, key):
        return val
    as_of = datetime.fromtimestamp(dev['telemetry_ts'][key] / 1000, REPORT_TZ).strftime('%d %b %H:%M')
    return f'<span class="na">{val}<br/><span style="font-size:9.5px;">as of {as_of}</span></span>'

def badge(text, color="grey"):
    return f'<span class="badge" style="background:{BADGE_COLORS.get(color, color)};">{text}</span>'

def kpi(value, label, color):
    return f'<div class="kpi"><div class="v" style="color:{color};">{value}</div><div class="l">{label}</div></div>'

def kv(label, value):
    return f'<div class="kv"><span class="k">{label}:</span> <b>{value}</b></div>'

def trends_section(blocks):
    """blocks: list of chart HTML blocks; the heading is kept on the same page as the first."""
    if isinstance(blocks, str):
        blocks = [blocks]
    first = f'<div style="page-break-inside:avoid;break-inside:avoid;"><h3>24-Hour Time Series Trends</h3>{blocks[0] if blocks else ""}</div>'
    return f'<div class="section">{first}{"".join(blocks[1:])}</div>'

def report_page(title, header_title, header_bg, meta_html, kpis_html, body_html, footer_text):
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>{REPORT_CSS}</style>
</head>
<body>
    <div class="report">
        <div class="hdr" style="background: {header_bg};">
            <h1>{header_title}</h1>
            <div class="meta">{meta_html}</div>
        </div>
        <div class="kpis">{kpis_html}</div>
        {body_html}
        <div class="footer">{footer_text} &bull; Virtuoso NetSoft Infrastructure Operations</div>
    </div>
</body>
</html>
"""

def _report_meta(devices_summary, extra=""):
    now = datetime.now(REPORT_TZ)
    if devices_summary and devices_summary[0].get('historical'):
        start = datetime.fromtimestamp(devices_summary[0]['series_start_ts'] / 1000, REPORT_TZ)
        return (f"Report Date: <b>{start.strftime('%d %B %Y')}</b> (00:00 - 24:00 IST) &nbsp;|&nbsp; "
                f"Generated At: <b>{now.strftime('%d %b %Y %H:%M IST')}</b>{extra}")
    return f"Date: <b>{now.strftime('%d %B %Y')}</b> &nbsp;|&nbsp; Generated At: <b>{now.strftime('%H:%M:%S IST')}</b>{extra}"

def _is_historical(devices_summary):
    return bool(devices_summary) and devices_summary[0].get('historical', False)

def _live_word(devices_summary):
    """'Live' for the rolling 24h report; 'End-of-Day' for a past day's report."""
    return "End-of-Day" if _is_historical(devices_summary) else "Live"

def _fmt_sync(last_activity):
    """'2026-10-13 20:54:03' -> '13 Oct<br/>20:54:03' (kept as-is if not a timestamp)."""
    try:
        dt = datetime.strptime(last_activity, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return last_activity
    return f'<span class="nw">{dt.strftime("%d %b %Y")}</span><br/><span class="nw">{dt.strftime("%H:%M:%S")}</span>'

def _valid_float(val):
    """float(val), or None when missing/non-numeric/sensor-offline."""
    try:
        f = float(val)
    except (ValueError, TypeError):
        return None
    return None if f in SENSOR_OFFLINE_VALUES else f

# ==============================================================================
# 1. SEPARATE DG SET 24H REPORT HTML
# ==============================================================================
def generate_dg_set_html(devices_summary):
    dg_devices = sorted(
        [d for d in devices_summary if "dg set" in d['name'].lower() or d['type'] == 'woodward_kg1500'],
        key=lambda d: d['name']
    )
    total_dg = len(dg_devices)
    active_dg = sum(1 for d in dg_devices if d['is_active'])
    running_dg = sum(1 for d in dg_devices
                     if live_val(d, 'dg_status') == 'RUNNING' or (_valid_float(live_val(d, 'engine_rpm')) or 0) > 100)
    total_alarms = sum(d['alarms_count'] for d in dg_devices)
    # energy_kwh is a cumulative meter, so 24h energy is its increase over the window
    energy_24h = sum(max(d['agg_24h'].get('energy_kwh_24h_delta', 0), 0) for d in dg_devices)

    rows_html = ""
    for d in dg_devices:
        tel, agg = d['telemetry'], d['agg_24h']
        online = badge("ONLINE", "green") if d['is_active'] else badge("OFFLINE", "red")
        dg_state = live_val(d, 'dg_status')
        state_badge = badge(dg_state, "teal" if dg_state == 'RUNNING' else "grey") if dg_state else badge("NO DATA", "grey")

        rows_html += f"""
        <tr>
            <td><div class="name" style="color:#0d47a1;">{d['name']}</div><div style="margin-top:5px;">{online}</div></td>
            <td class="c">{state_badge}</td>
            <td>
                {kv(f"{_live_word(devices_summary)} Power", fmt_latest(d, 'power_kw', "kW"))}
                {kv("24h Peak", fmt_val(agg.get('power_kw_24h_max'), "kW"))}
                {kv("24h Energy", fmt_val(agg.get('energy_kwh_24h_delta'), "kWh", 0))}
                {kv("Meter", fmt_latest(d, 'energy_kwh', "kWh", 0))}
            </td>
            <td>
                {kv("Fuel Level", fmt_latest(d, 'fuel_level', "%"))}
                {kv("24h Avg / Min", f"{fmt_val(agg.get('fuel_level_24h_avg'), '%')} / {fmt_val(agg.get('fuel_level_24h_min'), '%')}")}
                {kv("Battery", fmt_latest(d, 'battery_voltage', "V"))}
            </td>
            <td>
                {kv("Coolant", fmt_latest(d, 'coolant_temp', "°C"))}
                {kv("Oil Pressure", fmt_latest(d, 'oil_pressure', "bar"))}
                {kv("Engine RPM", fmt_latest(d, 'engine_rpm', "", 0))}
                {kv("Run Hours", fmt_latest(d, 'run_hours', "hrs"))}
                {kv("Starts", fmt_latest(d, 'engine_starts', "", 0))}
            </td>
            <td class="muted">{_fmt_sync(d['last_activity'])}</td>
        </tr>
        """

    kpis_html = (
        kpi(total_dg, "Total DG Sets", "#0d47a1")
        + kpi(active_dg, "Active / Online", "#2e7d32")
        + kpi(running_dg, "Currently Running", "#00796b")
        + kpi(f"{energy_24h:,.1f} kWh", "24h Energy Generated", "#ef6c00")
        + kpi(total_alarms, "Alarms Raised" if _is_historical(devices_summary) else "Active Alarms", "#c62828" if total_alarms > 0 else "#2e7d32")
    )

    dg_start = dg_devices[0]['series_start_ts'] if dg_devices else 0
    dg_charts = [
        chart_card(title, unit, [(d['name'], SERIES_COLORS[i % len(SERIES_COLORS)], d['series_24h'].get(key, [])) for i, d in enumerate(dg_devices)], dg_start, height=180)
        for title, key, unit in [("Power Output", "power_kw", "kW"), ("Fuel Level", "fuel_level", "%"),
                                 ("Battery Voltage", "battery_voltage", "V"), ("Coolant Temperature", "coolant_temp", "°C")]
    ] if dg_devices else [_no_data("No DG Set devices found")]

    body_html = f"""
    <div class="section">
        <h3>DG Sets Detailed 24h Operational Breakdown</h3>
        <table class="data">
            <thead>
                <tr style="background-color:#e3f2fd; border-bottom:2px solid #bbdefb;">
                    <th style="width:12%;">DG Set</th>
                    <th class="c" style="width:12%;">State</th>
                    <th style="width:21%;">Power &amp; Energy</th>
                    <th style="width:21%;">Fuel &amp; Battery</th>
                    <th style="width:23%;">Engine Health</th>
                    <th style="width:11%;">Last Sync</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    {trends_section(dg_charts)}
    """

    return report_page(
        "Daily 24-Hour DG Sets Operations Report",
        "Daily 24-Hour Diesel Generator (DG Set) Operations Report",
        "linear-gradient(135deg, #0d47a1 0%, #1976d2 100%)",
        _report_meta(devices_summary), kpis_html, body_html,
        "Automated DG Set 24h Operations PDF Report"
    )

# ==============================================================================
# 2. SEPARATE LT PANELS 24H REPORT HTML
# ==============================================================================
def generate_lt_panels_html(devices_summary):
    lt_master = next((d for d in devices_summary if "LT Panel" in d['name'] or d['type'] in ('LT Panel Master Profile', 'LT Panels Profile')), None)
    panels_def = LT_PANELS

    tel = lt_master['telemetry'] if lt_master else {}
    agg = lt_master['agg_24h'] if lt_master else {}
    is_active = lt_master['is_active'] if lt_master else False

    def energized(prefix):
        return (_valid_float(live_val(lt_master, f"{prefix}_voltage")) or 0) > 0

    total_panels = len(panels_def)
    active_panels = sum(1 for _, prefix in panels_def if energized(prefix))
    total_kw = sum(_valid_float(live_val(lt_master, f"{prefix}_power")) or 0 for _, prefix in panels_def)
    live_freqs = [f for _, prefix in panels_def if energized(prefix)
                  for f in [_valid_float(live_val(lt_master, f"{prefix}_frequency"))] if f and 40 <= f <= 70]
    grid_freq = f"{sum(live_freqs) / len(live_freqs):.2f} Hz" if live_freqs else "N/A"

    rows_html = ""
    for name, prefix in panels_def:
        if energized(prefix):
            state = badge("ENERGIZED", "green")
        elif not is_fresh(lt_master, f"{prefix}_voltage"):
            state = badge("NO LIVE DATA", "grey")
        elif _valid_float(tel.get(f"{prefix}_voltage")) is None:
            state = badge("NO DATA", "grey")
        else:
            state = badge("STANDBY", "amber")

        rows_html += f"""
        <tr>
            <td class="name" style="color:#2e7d32;">{name}</td>
            <td class="c">{state}</td>
            <td class="r"><b>{fmt_latest(lt_master, f"{prefix}_power", "kW", 2)}</b></td>
            <td class="r">{fmt_latest(lt_master, f"{prefix}_voltage", "V")}</td>
            <td class="r">{fmt_latest(lt_master, f"{prefix}_current", "A")}</td>
            <td class="r">{fmt_latest(lt_master, f"{prefix}_frequency", "Hz", 2)}</td>
            <td class="r">
                <div class="kv">{fmt_val(agg.get(f"{prefix}_power_24h_avg"), "kW", 2)}</div>
                <div class="kv muted">peak {fmt_val(agg.get(f"{prefix}_power_24h_max"), "kW", 2)}</div>
            </td>
        </tr>
        """

    master_badge = badge("MASTER ONLINE", "green") if is_active else badge("MASTER OFFLINE", "red")
    kpis_html = (
        kpi(total_panels, "Sub-Panels Monitored", "#1b5e20")
        + kpi(active_panels, "Circuits Energized", "#2e7d32")
        + kpi(f"{total_kw:,.1f} kW", f"Total {_live_word(devices_summary)} Power Load", "#2e7d32")
        + kpi(grid_freq, f"Avg Grid Frequency ({_live_word(devices_summary)})", "#00796b")
    )

    lt_series = lt_master['series_24h'] if lt_master else {}
    lt_start = lt_master['series_start_ts'] if lt_master else 0
    lt_cards = [
        f'<div style="width:49%;">{chart_card(name, "kW", [(name, SERIES_COLORS[0], lt_series.get(f"{prefix}_power", []))], lt_start, width=440, height=170)}</div>'
        for name, prefix in panels_def
    ]
    # Two charts per row; each row stays on one page
    lt_charts = [
        f'<div style="display:flex;justify-content:space-between;page-break-inside:avoid;break-inside:avoid;">{"".join(lt_cards[i:i + 2])}</div>'
        for i in range(0, len(lt_cards), 2)
    ]

    body_html = f"""
    <div class="section">
        <h3>LT Sub-Panels Electrical Readings <span class="sub">({_live_word(devices_summary)} values + 24h statistics)</span></h3>
        <table class="data">
            <thead>
                <tr style="background-color:#e8f5e9; border-bottom:2px solid #c8e6c9;">
                    <th style="width:14%;">Sub-Panel</th>
                    <th class="c" style="width:15%;">State</th>
                    <th class="r" style="width:14%;">{_live_word(devices_summary)} Power</th>
                    <th class="r" style="width:13%;">Voltage</th>
                    <th class="r" style="width:13%;">Current</th>
                    <th class="r" style="width:13%;">Frequency</th>
                    <th class="r" style="width:18%;">24h Avg / Peak Power</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="muted" style="margin-top:8px;">Greyed values with an "as of" date were not updated during the report period and are excluded from the totals above.</div>
    </div>
    {trends_section(lt_charts)}
    """

    return report_page(
        "Daily 24-Hour LT Panels Electrical Load Report",
        "Daily 24-Hour Low Voltage (LT) Panels Electrical Report",
        "linear-gradient(135deg, #1b5e20 0%, #388e3c 100%)",
        _report_meta(devices_summary, f" &nbsp;|&nbsp; Status: {master_badge}"), kpis_html, body_html,
        "Automated LT Panels 24h Electrical PDF Report"
    )

# ==============================================================================
# 3. SEPARATE FIRE SUPPRESSION 24H REPORT HTML
# ==============================================================================
def generate_fire_suppression_html(devices_summary):
    fire_dev = next((d for d in devices_summary if "Fire" in d['name'] or d['type'] == 'LT Panel Fire Profile'), None)
    tel = fire_dev['telemetry'] if fire_dev else {}
    agg = fire_dev['agg_24h'] if fire_dev else {}
    alarms_count = fire_dev['alarms_count'] if fire_dev else 0

    def flag(key):
        """True/False from a boolean telemetry key, None when the key is not reported."""
        v = live_val(fire_dev, key)
        return None if v is None else str(v).lower() == 'true'

    relay_online = flag('relay_online')
    low_press_ok = flag('low_pressure')
    high_press_ok = flag('high_pressure')
    cyl_statuses = [flag(f'cylinder_pressure_{i}') for i in range(1, 10)]
    cyl_reported = [s for s in cyl_statuses if s is not None]
    cyl_ok_count = sum(1 for s in cyl_reported if s)
    cyl_all_ok = bool(cyl_reported) and cyl_ok_count == len(cyl_reported)

    has_data = bool(cyl_reported) or relay_online is not None
    sys_status_badge = badge("NO DATA IN PERIOD", "grey") if not has_data and alarms_count == 0 else badge("SYSTEM NORMAL", "green") if alarms_count == 0 else badge(f"{alarms_count} ALARM(S) {'RAISED' if _is_historical(devices_summary) else 'ACTIVE'}", "red")

    def state_kpi(ok, ok_text, bad_text, label):
        if ok is None:
            return kpi("NO DATA", label, "#9ca3af")
        return kpi(ok_text if ok else bad_text, label, "#2e7d32" if ok else "#c62828")

    kpis_html = (
        state_kpi(relay_online, "ONLINE", "OFFLINE", "Relay Gateway State")
        + state_kpi(low_press_ok, "NORMAL", "LOW", "Low Pressure Line")
        + state_kpi(high_press_ok, "NORMAL", "HIGH ALARM", "High Pressure Line")
        + (kpi("NO DATA", "Cylinders Pressure", "#9ca3af") if not cyl_reported else kpi(f"{cyl_ok_count} / 9 OK", "Cylinders Pressure", "#2e7d32" if cyl_all_ok and len(cyl_reported) == 9 else "#c62828" if cyl_ok_count < len(cyl_reported) else "#ef6c00"))
    )

    rows_html = ""
    for i in range(1, 10):
        cyl = cyl_statuses[i - 1]
        di = flag(f"di{i}")
        cyl_badge = badge("NO DATA", "grey") if cyl is None else badge("PRESSURE OK", "green") if cyl else badge("PRESSURE LOW", "red")
        di_badge = (badge("NO DATA", "grey") if f"di{i}" in tel else badge("NOT REPORTED", "grey")) if di is None else badge("CLOSED / NORMAL", "green") if di else badge("OPEN / CHECK", "amber")

        ok_share = agg.get(f"cylinder_pressure_{i}_24h_avg")
        samples = agg.get(f"cylinder_pressure_{i}_24h_count", 0)
        ok_24h = (f'{fmt_val(ok_share * 100, "% OK")}<div class="muted">{samples:,} sample{"s" if samples != 1 else ""}</div>'
                  if ok_share is not None else '<span class="na">No samples in period</span>')

        if cyl is None:
            health = '<span class="na">No Data</span>'
        elif not cyl:
            health = '<b style="color:#c62828;">Attention: Low Pressure</b>'
        elif di is False:
            health = '<b style="color:#ef6c00;">Check Digital Input</b>'
        else:
            health = '<b style="color:#2e7d32;">Normal</b>'

        rows_html += f"""
        <tr>
            <td class="name" style="color:#c62828;">Fire Suppression {i}</td>
            <td class="c">{cyl_badge}</td>
            <td class="c">{di_badge}</td>
            <td>{ok_24h}</td>
            <td>{health}</td>
        </tr>
        """

    fire_series = fire_dev['series_24h'] if fire_dev else {}
    fire_start = fire_dev['series_start_ts'] if fire_dev else 0
    fire_rows = [("Relay Gateway Online", fire_series.get('relay_online', []))] + [
        (f"Cylinder {i} Pressure", fire_series.get(f"cylinder_pressure_{i}", [])) for i in range(1, 10)
    ]
    fire_charts = f"""
    <div style="page-break-inside:avoid;break-inside:avoid;border:1px solid #e0e0e0;border-radius:6px;padding:12px 14px;background:#fcfcfb;">
        <div style="font-size:13px;font-weight:bold;color:{INK};">Safety Signal Status Timeline <span style="font-weight:normal;color:{INK_MUTED};">(30-min buckets)</span></div>
        {svg_status_strip(fire_rows, fire_start)}
    </div>
    """

    body_html = f"""
    <div class="section">
        <h3>Fire Panels &amp; Cylinder Safety Status</h3>
        <table class="data">
            <thead>
                <tr style="background-color:#ffebee; border-bottom:2px solid #ffcdd2;">
                    <th style="width:20%;">Panel Zone</th>
                    <th class="c" style="width:18%;">Cylinder Pressure</th>
                    <th class="c" style="width:18%;">Digital Input (DI)</th>
                    <th style="width:22%;">24h Pressure Health</th>
                    <th style="width:22%;">Status</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    {trends_section(fire_charts)}
    """

    return report_page(
        "Daily 24-Hour Fire Suppression Safety Report",
        "Daily 24-Hour Fire Suppression Safety Report",
        "linear-gradient(135deg, #b71c1c 0%, #c62828 100%)",
        _report_meta(devices_summary, f" &nbsp;|&nbsp; Overall Status: {sys_status_badge}"), kpis_html, body_html,
        "Automated Fire Suppression 24h Safety PDF Report"
    )

# ==============================================================================
# 4. SEPARATE RO PLANT 24H REPORT HTML
# ==============================================================================
def generate_ro_plant_html(devices_summary):
    ro_dev = next((d for d in devices_summary if "RO Plant" in d['name'] or d['type'] == 'RO System Profile'), None)
    tel = ro_dev['telemetry'] if ro_dev else {}
    agg = ro_dev['agg_24h'] if ro_dev else {}
    ro_status = tel.get('status', 'OFFLINE')
    last_data = ro_dev['last_activity'] if ro_dev else "No activity"

    tds, flow, ph = _valid_float(tel.get('tds')), _valid_float(tel.get('water_flow')), _valid_float(tel.get('ph'))

    def compliance(text, color):
        return f'<b style="color:{BADGE_COLORS[color]};">{text}</b>'

    tds_c = (compliance("No Data", "grey") if tds is None else compliance("Optimal (&lt; 200 ppm)", "green") if tds < 200
             else compliance("Acceptable (200-500 ppm)", "amber") if tds <= 500 else compliance("High (&gt; 500 ppm)", "red"))
    flow_c = compliance("No Data", "grey") if flow is None else compliance("Normal Flow", "green") if flow > 0 else compliance("No Flow", "amber")
    press_c = compliance("No Data", "grey") if _valid_float(tel.get('pressure')) is None else compliance("Monitored", "blue")
    ph_c = (compliance("No Data", "grey") if ph is None else compliance("Balanced (6.5 - 8.5)", "green") if 6.5 <= ph <= 8.5
            else compliance("Out of Range (6.5 - 8.5)", "red"))

    def param_row(label, key, unit, comp, decimals=1):
        if ro_dev and key in tel and not is_fresh(ro_dev, key):
            comp = f'<span class="na">Last known: {re.sub("<[^>]+>", "", comp)}</span>'
        return f"""
        <tr>
            <td class="name" style="color:#0369a1;">{label}</td>
            <td class="r"><b>{fmt_latest(ro_dev, key, unit, decimals)}</b></td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_avg"), unit, decimals)}</td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_min"), unit, decimals)}</td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_max"), unit, decimals)}</td>
            <td>{comp}</td>
        </tr>
        """

    rows_html = (
        param_row("TDS (Total Dissolved Solids)", "tds", "ppm", tds_c, 0)
        + param_row("Permeate Water Flow Rate", "water_flow", "L/min", flow_c)
        + param_row("RO Membrane Pressure", "pressure", "psi", press_c)
        + param_row("pH Level", "ph", "", ph_c)
    )

    kpis_html = (
        kpi(fmt_latest(ro_dev, 'tds', "ppm", 0), "Latest TDS Level", "#0288d1")
        + kpi(fmt_val(agg.get('tds_24h_avg'), "ppm", 0), "24h Avg TDS", "#039be5")
        + kpi(fmt_latest(ro_dev, 'water_flow', "L/min"), "Permeate Water Flow", "#00796b")
        + kpi(fmt_latest(ro_dev, 'pressure', "psi"), "RO Pressure", "#2e7d32")
    )

    ro_series = ro_dev['series_24h'] if ro_dev else {}
    ro_start = ro_dev['series_start_ts'] if ro_dev else 0
    if any(v is not None for vals in ro_series.values() for v in vals):
        ro_charts = "".join(
            chart_card(title, unit, [(title, SERIES_COLORS[0], ro_series.get(key, []))], ro_start)
            for title, key, unit in [("TDS", "tds", "ppm"), ("Permeate Water Flow", "water_flow", "L/min"),
                                     ("RO Membrane Pressure", "pressure", "psi"), ("pH Level", "ph", "pH")]
        )
    else:
        ro_charts = _no_data()

    body_html = f"""
    <div class="section">
        <h3>Water Quality &amp; 24h Monitoring Metrics</h3>
        <table class="data">
            <thead>
                <tr style="background-color:#e1f5fe; border-bottom:2px solid #b3e5fc;">
                    <th style="width:22%;">Parameter</th>
                    <th class="r" style="width:16%;">Latest Reading</th>
                    <th class="r" style="width:12%;">24h Average</th>
                    <th class="r" style="width:12%;">24h Minimum</th>
                    <th class="r" style="width:12%;">24h Maximum</th>
                    <th style="width:26%;">Quality Compliance</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="muted" style="margin-top:8px;">Greyed readings with an "as of" date were not updated during the report period (device last activity: {last_data}). Compliance is evaluated on the latest reading.</div>
    </div>
    {trends_section(ro_charts)}
    """

    return report_page(
        "Daily 24-Hour RO Plant Water Quality Report",
        "Daily 24-Hour RO Plant Water Quality &amp; Treatment Report",
        "linear-gradient(135deg, #0288d1 0%, #039be5 100%)",
        _report_meta(devices_summary, f" &nbsp;|&nbsp; Status: {badge(ro_status, 'blue') if is_fresh(ro_dev, 'status') else badge('NO DATA IN PERIOD', 'grey')}"), kpis_html, body_html,
        "Automated RO Plant Water Treatment 24h PDF Report"
    )

# ==============================================================================
# GENERATE ALL 4 SEPARATE PDFS & EMAIL DISPATCH
# ==============================================================================
def _report_day(summary):
    if summary and summary[0].get('historical'):
        return datetime.fromtimestamp(summary[0]['series_start_ts'] / 1000, REPORT_TZ)
    return datetime.now(REPORT_TZ)

def generate_all_separate_pdfs(summary=None):
    if not summary:
        summary = fetch_master_devices_summary()

    date_fn = _report_day(summary).strftime('%Y%m%d')

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

def send_email_with_separate_pdfs(reports, recipients_override=None, report_day=None):
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
    date_str = (report_day or datetime.now(REPORT_TZ)).strftime('%d %b %Y')

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
    
    report_date = next((a.split("=", 1)[1] for a in args if a.startswith("--date=")), None)

    print(f"Fetching master devices summary from ThingsBoard{f' for {report_date}' if report_date else ''}...")
    summary = fetch_master_devices_summary(report_date)
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
                recipients = a.split("=", 1)[1]
        send_email_with_separate_pdfs(reports, recipients, _report_day(summary))

    if not args:
        print("\nUsage:")
        print("  python3 generate_separate_pdfs_report.py --preview              (Generates HTML and 4 separate PDF preview files)")
        print("  python3 generate_separate_pdfs_report.py --send-now             (Sends email with 4 separate PDF attachments)")
        print("  python3 generate_separate_pdfs_report.py --send-now --to=a@b.com (Sends report to specific email)")
        print("  python3 generate_separate_pdfs_report.py --preview --date=2026-10-03 (Report for one past IST day)")

if __name__ == "__main__":
    main()
