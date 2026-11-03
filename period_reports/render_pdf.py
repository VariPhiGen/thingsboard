"""Period report -> HTML (rendered to PDF by the pdf-generator service). Same look as the daily PDFs."""
from datetime import datetime
from html import escape

from infra_reports.charts import AXIS, GRID, INK, INK_2, INK_MUTED, SERIES_COLORS, fmt_tick, nice_ticks, no_data
from infra_reports.config import REPORT_TZ
from infra_reports.layout import REPORT_CSS, badge, kpi

from .period import CATEGORIES, SEVERITY_ORDER

PDF_ALARM_ROWS = 60
PDF_HISTORY_ROWS = 80
SEV_COLOR = {"CRITICAL": "red", "MAJOR": "amber", "MINOR": "amber", "WARNING": "amber", "OK": "green",
             "NO DATA": "grey", "INDETERMINATE": "grey"}
EXTRA_CSS = """
.report { max-width: 1040px; }
.kpis { flex-wrap: wrap; }
.kpi { min-width: 120px; }
table.data td, table.data th { padding: 7px 6px; }
table.data thead tr { background: #f3f4f6; border-bottom: 2px solid #e5e7eb; }
.section h4 { margin: 14px 0 8px; font-size: 13px; color: #374151; }
.note { font-size: 11px; color: #6b7280; margin: 6px 0 10px; line-height: 1.5; }
.pb { page-break-before: always; break-before: page; }
.section h3, .section h4 { page-break-after: avoid; break-after: avoid; }
table.data thead { display: table-header-group; }
table.data tr { page-break-inside: avoid; break-inside: avoid; }
"""


def ts_str(ts, fmt="%d %b %H:%M"):
    return datetime.fromtimestamp(ts / 1000, REPORT_TZ).strftime(fmt) if ts else "&mdash;"


def f(v, d=1, unit=""):
    if v is None:
        return '<span class="na">&mdash;</span>'
    s = f"{v:,.{d}f}"
    return f"{s}{(' ' + unit) if unit else ''}"


def dur(ms):
    if not ms or ms < 0:
        return "&mdash;"
    m = int(ms // 60000)
    return f"{m // 1440} d {m % 1440 // 60} h" if m >= 1440 else (f"{m // 60} h {m % 60:02d} m" if m >= 60 else f"{m} min")


def table(headers, rows, widths=None, align=None):
    align = align or {}
    def width(i):
        return ' style="width:%s"' % widths[i] if widths and widths[i] else ""
    th = "".join(f'<th class="{align.get(i, "")}"{width(i)}>{h}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{align.get(i, "")}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
                   for r in rows)
    return f'<table class="data"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def svg_daily_bars(days, series, unit, width=980, height=200):
    """Grouped daily bars. series: [(label, color, [value per day or None])]."""
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if not vals or max(vals) <= 0:
        return no_data("No activity in the report period")
    ml, mr, mt, mb = 56, 10, 10, 34
    pw, ph = width - ml - mr, height - mt - mb
    yt = nice_ticks(0, max(vals))
    y1 = yt[-1]
    n, k = len(days), len(series)
    slot = pw / n
    bw = max(2.0, min(18.0, slot * 0.8 / k))
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             f'style="display:block;font-family:Arial,sans-serif;">']
    for t in yt:
        y = mt + ph - t / y1 * ph
        parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                     f'<text x="{ml - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="{INK_MUTED}">{fmt_tick(t)}</text>')
    parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{mt + ph}" y2="{mt + ph}" stroke="{AXIS}"/>')
    every = 1 if n <= 10 else (2 if n <= 20 else 3)
    for i, day in enumerate(days):
        x0 = ml + i * slot + (slot - bw * k) / 2
        for j, (_, color, vs) in enumerate(series):
            v = vs[i]
            if v is None or v <= 0:
                continue
            h = v / y1 * ph
            parts.append(f'<rect x="{x0 + j * bw:.1f}" y="{mt + ph - h:.1f}" width="{bw - 1:.1f}" height="{h:.1f}" fill="{color}"/>')
        if i % every == 0:
            label = datetime.fromisoformat(day).strftime("%d %b")
            parts.append(f'<text x="{ml + (i + 0.5) * slot:.1f}" y="{height - 12}" text-anchor="middle" font-size="11" fill="{INK_MUTED}">{label}</text>')
    parts.append("</svg>")
    legend = "".join(f'<span style="margin-right:14px;white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
                     f'background:{c};border-radius:2px;margin-right:5px;vertical-align:-1px;"></span>{escape(l)}</span>'
                     for l, c, _ in series) if k > 1 else ""
    return f'<div style="font-size:11px;color:{INK_2};margin:2px 0 6px;">{legend}<span style="color:{INK_MUTED};">({escape(unit)} per day)</span></div>' + "".join(parts)


def chart_card(title, body):
    return (f'<div style="page-break-inside:avoid;break-inside:avoid;border:1px solid #e0e0e0;border-radius:6px;'
            f'padding:10px 12px 8px;margin-bottom:12px;background:#fcfcfb;">'
            f'<div style="font-size:13px;font-weight:bold;color:{INK};">{escape(title)}</div>{body}</div>')


def day_values(dev, key, getter=None):
    by = {d["date"]: d for d in dev["days"]}
    return lambda days: [(getter(by[x]) if getter else by[x].get(key)) if x in by else None for x in days]


# ------------------------------------------------------------------ sections
def outlook_section(p):
    rows = []
    for d in p["devices"]:
        o = d["outlook"]
        sev = o["severity"] or "NO DATA"
        health = f'{o["health"]:.0f}' if o["health"] is not None else "&mdash;"
        extra = []
        if d["category"] == "dg":
            if o["service_due_h"] is not None:
                due = o["service_due_h"]
                extra.append(f'Service {"overdue by " + f(-due, 0) if due < 0 else "due in " + f(due, 0)} run-h')
            if o["days_since_run"] is not None:
                extra.append(f'last run {f(o["days_since_run"], 0)} d ago')
            if o["fuel_pct"] is not None:
                extra.append(f'fuel {"&ge;100" if o["fuel_pct"] >= 99.95 else f(o["fuel_pct"], 0)} %'
                             + (f' (~{f(o["fuel_runtime_h"], 1)} h)' if o["fuel_runtime_h"] is not None else ""))
        lm = o["last_maintenance"]
        last = (f'{ts_str(lm["ts"], "%d %b %Y")}<div class="muted">{escape(str(lm.get("type") or ""))}</div>'
                if lm else '<span class="na">None recorded</span>')
        rows.append([
            f'<span class="name">{escape(d["name"])}</span><div class="muted">{CATEGORIES[d["category"]]}</div>',
            f'{badge(sev, SEV_COLOR.get(sev, "grey"))}<div class="muted" style="margin-top:3px;">Health {health}</div>',
            (escape(o["top_issue"]) if o["top_issue"] and o["top_issue"] != "None" else "No issues")
            + (f'<div class="muted">{" &middot; ".join(extra)}</div>' if extra else ""),
            escape(o["recommendation"] or "&mdash;"),
            last,
        ])
    return (f'<div class="section"><h3>Maintenance Outlook <span class="sub">(predictive maintenance status at '
            f'{p["generated_at"].strftime("%d %b %Y %H:%M IST")})</span></h3>'
            + table(["Equipment", "Status", "Main finding", "Recommended action", "Last maintenance"],
                    rows, ["17%", "12%", "28%", "28%", "15%"]) +
            '<div class="note">Health 80-100 OK, 40-79 Warning, 0-39 Critical. Service due counts engine run-hours '
            'since the last recorded service.</div></div>')


def dg_section(p, devs):
    days = p["days"]
    rows = []
    for d in devs:
        t = d["totals"]
        fuel = f(t["fuel_consumed_pct"], 1, "%") if t["fuel_consumed_pct"] is not None else '<span class="na">&mdash;</span>'
        if t["fuel_consumed_pct"] is not None and t["fuel_lower_bound"]:
            fuel = "&ge; " + fuel
        rows.append([
            f'<span class="name">{escape(d["name"])}</span>',
            f(t["run_hours"], 1), str(t["runs"]), f(t["energy_kwh"], 0),
            fuel, f'{f(t["refuelled_pct"], 1, "%")}<div class="muted">{t["refuels"]} refuel(s)</div>',
            f(t["battery_voltage"] and t["battery_voltage"]["min"], 1, "V"),
            f(t["coolant_temp"] and t["coolant_temp"]["max"], 0, "&deg;C"),
            f(d["availability_pct"], 1, "%"), str(len(d["alarms"])),
        ])
    al = {i: "r" for i in range(1, 10)}
    html = table(["DG", "Run hours", "Runs", "Energy kWh", "Fuel used", "Refuelled", "Battery min", "Coolant max",
                  "Data", "Alarms"], rows, ["14%"] + [None] * 9, al)
    colors = SERIES_COLORS
    hrs = [(d["name"], colors[i % 8], day_values(d, "run_hours")(days)) for i, d in enumerate(devs)]
    kwh = [(d["name"], colors[i % 8], day_values(d, "energy_kwh")(days)) for i, d in enumerate(devs)]
    charts = (chart_card("DG run hours per day", svg_daily_bars(days, hrs, "hours")) +
              chart_card("DG energy per day", svg_daily_bars(days, kwh, "kWh")))
    note = ('<div class="note">Fuel is in % of the tank sender span. "&ge;" marks periods that start or end with the tank '
            'above the sender\'s full point, where some consumption is hidden. Energy is integrated from measured power; '
            'battery minimum includes cranking dips.</div>')
    return f'<div class="section"><h3>DG Sets</h3>{html}{note}{charts}</div>'


def lt_section(p, devs):
    out = ""
    days = p["days"]
    for d in devs:
        rows, series = [], []
        for i, (key, fd) in enumerate(d["feeders"].items()):
            v, c, pw, fq = fd["voltage"], fd["current"], fd["power"], fd["frequency"]
            rows.append([
                f'<span class="name">{escape(fd["label"])}</span>', f(fd["energy_kwh"], 0),
                f'{f(v and v["avg"], 0)}<div class="muted">{f(v and v["min"], 0)} - {f(v and v["max"], 0)}</div>',
                f'{f(c and c["avg"], 0)}<div class="muted">max {f(c and c["max"], 0)}</div>',
                f'{f(pw and pw["avg"], 1)}<div class="muted">max {f(pw and pw["max"], 1)}</div>',
                f'{f(fq and fq["min"], 2)} - {f(fq and fq["max"], 2)}', f(fd.get("pf_avg"), 2),
                f(fd["coverage_pct"], 1, "%"),
            ])
            by = {x["date"]: x.get("energy_kwh") for x in fd["days"]}
            series.append((fd["label"], SERIES_COLORS[i % 8], [by.get(x) for x in days]))
        al = {i: "r" for i in range(1, 8)}
        out += (f'<h4>{escape(d["name"])}</h4>' +
                table(["Feeder", "Energy kWh", "Voltage V avg", "Current A avg", "Power kW avg", "Frequency Hz",
                       "PF avg", "Data"], rows, ["20%"] + [None] * 7, al) +
                chart_card("Feeder energy per day", svg_daily_bars(days, series, "kWh")))
    return (f'<div class="section"><h3>LT Panels</h3>{out}<div class="note">Energy from 30-minute average power. '
            'Power factor estimated from average power, voltage and current. Feeders without readings in the period are '
            'not listed.</div></div>')


def ro_section(p, devs):
    rows = []
    for d in devs:
        t = d["totals"]
        def st(k, dd=1, u=""):
            s = t.get(k)
            return (f'{f(s["avg"], dd, u)}<div class="muted">{f(s["min"], dd)} - {f(s["max"], dd)}</div>'
                    if s else '<span class="na">&mdash;</span>')
        rows.append([f'<span class="name">{escape(d["name"])}</span>', st("tds_ppm", 0, "ppm"), st("ec_us_cm", 0, "&micro;S/cm"),
                     st("temperature_c", 1, "&deg;C"), st("ph", 2), st("pressure", 1, "bar"),
                     f(d["availability_pct"], 1, "%"), str(len(d["alarms"]))])
    days = p["days"]
    tds = [(d["name"], SERIES_COLORS[i % 8], day_values(d, None, lambda x: (x["stats"].get("tds_ppm") or {}).get("avg"))(days))
           for i, d in enumerate(devs)]
    return (f'<div class="section"><h3>RO Plant</h3>' +
            table(["Plant", "Product TDS", "EC", "Water temp", "pH", "Pressure", "Data", "Alarms"], rows,
                  ["16%"] + [None] * 7, {i: "r" for i in range(1, 8)}) +
            chart_card("Average product-water TDS per day", svg_daily_bars(days, tds, "ppm")) +
            '<div class="note">Values are period average with min - max below. A rising TDS trend indicates membrane '
            'wear or fouling.</div></div>')


def fire_section(p, devs):
    out = ""
    for d in devs:
        rows = []
        for n, c in d["channels"].items():
            unstable = c["changes"] >= 20
            state = badge("NORMAL", "green") if c["last"] else badge("LOW", "red")
            rows.append([f"Cylinder {n}", f(c["ok_pct"], 1, "%"), str(c["low_days"]),
                         f'{c["changes"]:,}' + (' <span class="warn">unstable</span>' if unstable else ""), state])
        out += (f'<h4>{escape(d["name"])} <span class="muted">(data {f(d["availability_pct"], 1, "%")})</span></h4>' +
                table(["Channel", "Time at normal pressure", "Days with low pressure", "Signal changes", "State at period end"],
                      rows, ["20%", None, None, None, None], {1: "r", 2: "r", 3: "r"}))
    return (f'<div class="section"><h3>Fire Suppression</h3>{out}<div class="note">Hundreds of signal changes mean '
            'the pressure switch, its wiring or the data source is unreliable: the pressure state of that cylinder '
            'cannot be trusted until it is fixed.</div></div>')


def alarm_section(p):
    alarms = p["alarms"]
    if not alarms:
        return '<div class="section"><h3>Alarms</h3><div>No equipment alarms in the period.</div></div>'
    by = {}
    for a in alarms:
        key = (a["device"], a.get("type") or "Unknown", a.get("severity") or "")
        by.setdefault(key, []).append(a)
    rows = []
    for (dev, typ, sev), items in sorted(by.items(), key=lambda kv: (SEVERITY_ORDER.get(kv[0][2], 9), -len(kv[1]))):
        durs = [a["clear_ts"] - a["start_ts"] for a in items if a.get("clear_ts") and a.get("start_ts")]
        rows.append([escape(dev), escape(typ), badge(sev, SEV_COLOR.get(sev, "grey")), str(len(items)),
                     dur(sum(durs) / len(durs)) if durs else "&mdash;",
                     str(sum(1 for a in items if str(a.get("status", "")).startswith("ACTIVE")))])
    summary = table(["Equipment", "Alarm", "Severity", "Count", "Avg duration", "Still active"], rows,
                    ["20%", "34%", "12%", "9%", "14%", "11%"], {3: "r", 4: "r", 5: "r"})
    detail_rows = []
    for a in sorted(alarms, key=lambda a: a.get("start_ts") or 0, reverse=True)[:PDF_ALARM_ROWS]:
        d = (a["clear_ts"] - a["start_ts"]) if a.get("clear_ts") and a.get("start_ts") else None
        detail_rows.append([ts_str(a.get("start_ts")), escape(a["device"]), escape(a.get("type") or ""),
                            badge(a.get("severity") or "", SEV_COLOR.get(a.get("severity"), "grey")),
                            dur(d) if d is not None else '<span class="warn">active</span>'])
    more = (f'<div class="note">Showing the latest {PDF_ALARM_ROWS} of {len(alarms)} alarms. The Excel report lists all.</div>'
            if len(alarms) > PDF_ALARM_ROWS else "")
    return (f'<div class="section"><h3>Alarms <span class="sub">({len(alarms)} in the period)</span></h3>{summary}'
            f'<h4>Alarm log</h4>' + table(["Raised", "Equipment", "Alarm", "Severity", "Duration"], detail_rows,
                                           ["16%", "20%", "38%", "12%", "14%"]) + more + "</div>")


def history_section(p):
    rows = []
    for m in p["maintenance"]:
        extra = " &middot; ".join(x for x in [
            f'by {escape(str(m["technician"]))}' if m.get("technician") else "",
            f'at {f(float(m["run_hours"]), 1)} run-h' if _num(m.get("run_hours")) else "",
            f'parts: {escape(str(m["parts"]))}' if m.get("parts") else "",
        ] if x)
        rows.append((m["ts"], [ts_str(m["ts"]), escape(m["device"]), badge(m.get("type") or "Maintenance", "blue"),
                               escape(str(m.get("description") or "")) + (f'<div class="muted">{extra}</div>' if extra else "")]))
    for e in p["events"]:
        rows.append((e["ts"], [ts_str(e["ts"], "%d %b %H:%M" if e["kind"] != "Predictive" else "%d %b"),
                               escape(e["device"]), badge(e["kind"], "teal" if e["kind"] == "Fuel" else "amber"),
                               escape(e["text"])]))
    rows.sort(key=lambda r: r[0], reverse=True)
    n_manual = len(p["maintenance"])
    if not rows:
        body = '<div>No maintenance work or equipment events recorded in the period.</div>'
    else:
        body = table(["When", "Equipment", "Type", "Details"], [r for _, r in rows[:PDF_HISTORY_ROWS]],
                     ["14%", "18%", "14%", "54%"])
        if len(rows) > PDF_HISTORY_ROWS:
            body += f'<div class="note">Showing the latest {PDF_HISTORY_ROWS} of {len(rows)} entries. The Excel report lists all.</div>'
    hint = ('' if n_manual else '<div class="note">No maintenance work was logged in this period. Record work in the '
            '<b>Maintenance Management</b> on the Reports &amp; Maintenance dashboard (Work orders &gt; Record work done) so that it appears here.</div>')
    return (f'<div class="section"><h3>Maintenance &amp; Event History <span class="sub">({n_manual} maintenance '
            f'record(s), {len(p["events"])} automatic event(s))</span></h3>{body}{hint}</div>')


def _num(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def quality_section(p):
    notes = []
    if p["partial_days"]:
        notes.append(f'{", ".join(p["partial_days"])} is still in progress: values up to generation time.')
    for d in p["devices"]:
        if d["availability_pct"] is not None and d["availability_pct"] < 90:
            notes.append(f'{escape(d["name"])}: data received for {d["availability_pct"]:.0f}% of the period.')
        if d["alarms_excluded"]:
            notes.append(f'{escape(d["name"])}: {d["alarms_excluded"]} alarm notification(s) from invalid sensor '
                         'readings, duplicates or flickers excluded.')
    if not notes:
        return ""
    return '<div class="section"><h3>Data Quality</h3><ul class="note">' + "".join(f"<li>{n}</li>" for n in notes) + "</ul></div>"


def render_html(p):
    s, e = p["start"], p["end"]
    n = len(p["days"])
    span = s.strftime("%d %b %Y") if n == 1 else f'{s.strftime("%d %b %Y")} &ndash; {e.strftime("%d %b %Y")}'
    devs = p["devices"]
    by_cat = {c: [d for d in devs if d["category"] == c] for c in p["categories"]}
    scope = ", ".join(CATEGORIES[c] for c in p["categories"] if by_cat[c])
    dg = by_cat.get("dg", [])
    crit = sum(1 for a in p["alarms"] if a.get("severity") == "CRITICAL")
    attention = sum(1 for d in devs if d["outlook"]["severity"] in ("WARNING", "CRITICAL"))
    avail = [d["availability_pct"] for d in devs if d["availability_pct"] is not None]
    kpis = kpi(str(len(devs)), "Equipment", "#1f2937", escape(scope))
    kpis += kpi(f'{sum(avail) / len(avail):.1f}%' if avail else "&mdash;", "Data availability", "#0277bd")
    if dg:
        kpis += kpi(f(sum(d["totals"]["run_hours"] or 0 for d in dg), 1), "DG run hours", "#1f2937",
                    f'{sum(d["totals"]["runs"] for d in dg)} runs')
        kpis += kpi(f(sum(d["totals"]["energy_kwh"] or 0 for d in dg), 0), "DG energy kWh", "#1f2937")
    kpis += kpi(str(len(p["alarms"])), "Alarms", "#c62828" if crit else "#1f2937", f"{crit} critical")
    kpis += kpi(str(len(p["maintenance"])), "Maintenance jobs", "#00796b")
    kpis += kpi(str(attention), "Need attention now", "#ef6c00" if attention else "#2e7d32")

    body = outlook_section(p)
    builders = {"dg": dg_section, "lt": lt_section, "ro": ro_section, "fire": fire_section}
    for c in p["categories"]:
        if by_cat[c]:
            body += builders[c](p, by_cat[c])
    body += alarm_section(p) + history_section(p) + quality_section(p)
    who = f' &nbsp;|&nbsp; Generated by: <b>{escape(p["generated_by"])}</b>' if p.get("generated_by") else ""
    meta = (f'Period: <b>{span}</b> ({n} day{"s" if n != 1 else ""}, 00:00 - 24:00 IST) &nbsp;|&nbsp; '
            f'Generated: <b>{p["generated_at"].strftime("%d %b %Y %H:%M IST")}</b>{who}')
    title = f'{p["label"]} Equipment Performance &amp; Maintenance Report'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title><style>{REPORT_CSS}{EXTRA_CSS}</style></head>
<body><div class="report">
  <div class="hdr" style="background:#263238;"><h1>{title}</h1><div class="meta">{meta}</div></div>
  <div class="kpis">{kpis}</div>
  {body}
  <div class="footer">Virtuoso NetSoft Infrastructure Operations &bull; Preventive maintenance report &bull; {span}</div>
</div></body></html>"""
