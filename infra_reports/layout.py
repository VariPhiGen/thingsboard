"""Shared HTML building blocks for the PDF reports.

No emoji in PDF HTML: the PDF renderer has no emoji font and draws empty boxes.
Every device-supplied string goes through html.escape.
"""
from datetime import datetime
from html import escape

from .collect import period_of
from .config import REPORT_TZ
from .metrics import SENSOR_OFFLINE_VALUES, parse_value

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
.kpi .s { font-size: 10px; color: #6b7280; margin-top: 3px; }
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
.warn { color: #ef6c00; font-weight: bold; }
.kv { line-height: 1.6; margin-bottom: 2px; }
.kv .k { color: #6b7280; }
.muted { color: #6b7280; font-size: 11px; }
.footer { background: #f0f4f8; padding: 14px; text-align: center; font-size: 11.5px; color: #777777; border-top: 1px solid #e0e0e0; }
"""


def valid_float(val):
    """float(val), or None when missing / non-numeric / sensor-offline. Booleans are not numbers here."""
    if isinstance(val, bool) or str(val).strip().lower() in ("true", "false"):
        return None
    return parse_value(val)


def fmt_val(val, unit="", decimals=1):
    """Format a value for display; missing/invalid values never get a unit."""
    if val is None or str(val).strip() in ("", "N/A", "--"):
        return '<span class="na">N/A</span>'
    try:
        number = float(val)
    except (ValueError, TypeError):
        text = str(val).strip()
        return '<span class="na">Sensor Error</span>' if text.lower() == "error" else f'<span class="na">{escape(text)}</span>'
    if number in SENSOR_OFFLINE_VALUES:
        return '<span class="na">Sensor Offline</span>'
    return f'<span class="nw">{number:,.{decimals}f}{" " + escape(unit) if unit else ""}</span>'


def is_fresh(dev, key):
    """True when the device's latest value for key falls inside the report period."""
    if not dev:
        return False
    ts = dev.get("telemetry_ts", {}).get(key)
    return ts is not None and dev["series_start_ts"] <= ts <= dev.get("series_end_ts", ts)


def live_val(dev, key):
    """Latest value of key, or None when it is missing or older than the report period."""
    return dev["telemetry"].get(key) if is_fresh(dev, key) else None


def fmt_latest(dev, key, unit="", decimals=1):
    """fmt_val of the latest value; a value older than the report period is greyed and dated."""
    if not dev or key not in dev["telemetry"]:
        return fmt_val(None)
    val = fmt_val(dev["telemetry"][key], unit, decimals)
    if is_fresh(dev, key):
        return val
    as_of = datetime.fromtimestamp(dev["telemetry_ts"][key] / 1000, REPORT_TZ).strftime("%d %b %H:%M")
    return f'<span class="na">{val}<br/><span style="font-size:9.5px;">as of {as_of}</span></span>'


def badge(text, color="grey"):
    return f'<span class="badge" style="background:{BADGE_COLORS.get(color, color)};">{escape(str(text))}</span>'


def kpi(value, label, color, sub=""):
    sub_html = f'<div class="s">{sub}</div>' if sub else ""
    return f'<div class="kpi"><div class="v" style="color:{color};">{value}</div><div class="l">{label}</div>{sub_html}</div>'


def kv(label, value):
    return f'<div class="kv"><span class="k">{label}:</span> <b>{value}</b></div>'


def trends_section(blocks):
    """blocks: chart HTML blocks; the heading is kept on the same page as the first block."""
    if isinstance(blocks, str):
        blocks = [blocks]
    first = (f'<div style="page-break-inside:avoid;break-inside:avoid;"><h3>24-Hour Time Series Trends</h3>'
             f'{blocks[0] if blocks else ""}</div>')
    return f'<div class="section">{first}{"".join(blocks[1:])}</div>'


def excluded_alarms_count(devices):
    """Number of alarm notifications screened out of the counts as data-quality events."""
    return sum(n for d in devices for n in (d.get("alarms_excluded") or {}).values())


DATA_QUALITY_KPI_NOTE = "Excludes data-quality events"


def alarm_section(devices, historical):
    """Alarm counts by type and device; empty string when there are none."""
    types = sorted({t for d in devices for t in d.get("alarm_types", {})},
                   key=lambda t: -sum(d.get("alarm_types", {}).get(t, 0) for d in devices))
    excluded = excluded_alarms_count(devices)
    note = (f'<div class="muted" style="margin-top:8px;">Note: {excluded:,} automatic '
            f'notification{"s" if excluded != 1 else ""}{" during the day" if historical else ""} came from '
            f'monitoring data issues (missing or invalid sensor readings and repeated notifications), not from '
            f'equipment faults, and {"are" if excluded != 1 else "is"} not counted above.</div>') if excluded else ""
    if not types:
        if not excluded:
            return ""
        return f"""
    <div class="section">
        <h3>{"Alarms Raised During the Day" if historical else "Currently Active Alarms"}</h3>
        <div>No equipment alarms.</div>
        {note}
    </div>
    """
    head = "".join(f'<th class="r">{escape(d["name"])}</th>' for d in devices)
    rows = ""
    for t in types:
        counts = [d.get("alarm_types", {}).get(t, 0) for d in devices]
        cells = "".join(f'<td class="r">{c:,}</td>' for c in counts)
        rows += f'<tr><td>{escape(t)}</td>{cells}<td class="r"><b>{sum(counts):,}</b></td></tr>'
    title = "Alarms Raised During the Day" if historical else "Currently Active Alarms"
    return f"""
    <div class="section">
        <h3>{title} <span class="sub">(by type)</span></h3>
        <table class="data">
            <thead><tr style="background-color:#f3f4f6; border-bottom:2px solid #e5e7eb;">
                <th style="width:34%;">Alarm Type</th>{head}<th class="r">Total</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
        {note}
    </div>
    """


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


def report_meta(summary, extra=""):
    start_ts, _, historical = period_of(summary)
    now = datetime.now(REPORT_TZ)
    if historical:
        start = datetime.fromtimestamp(start_ts / 1000, REPORT_TZ)
        return (f"Report Date: <b>{start.strftime('%d %B %Y')}</b> (00:00 - 24:00 IST) &nbsp;|&nbsp; "
                f"Generated At: <b>{now.strftime('%d %b %Y %H:%M IST')}</b>{extra}")
    return f"Date: <b>{now.strftime('%d %B %Y')}</b> &nbsp;|&nbsp; Generated At: <b>{now.strftime('%H:%M:%S IST')}</b>{extra}"


def is_historical(summary):
    return period_of(summary)[2]


def live_word(summary):
    """'Live' for the rolling 24h report; 'End-of-Day' for a past day's report."""
    return "End-of-Day" if is_historical(summary) else "Live"


def fmt_sync(last_activity):
    """'2026-10-13 20:54:03' -> '13 Oct 2026<br/>20:54:03' (escaped as-is if not a timestamp)."""
    try:
        dt = datetime.strptime(last_activity, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return escape(str(last_activity))
    return f'<span class="nw">{dt.strftime("%d %b %Y")}</span><br/><span class="nw">{dt.strftime("%H:%M:%S")}</span>'
