"""Static inline-SVG charts (no JavaScript), so any HTML-to-PDF engine renders them."""
import math
from datetime import datetime
from html import escape

from .config import REPORT_TZ
from .metrics import BUCKET_MS

# Categorical order validated for colour-vision deficiency; colour follows the device, never its rank
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK_2, INK_MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

NO_DATA_TEXT = "No valid readings in the report period"


def fmt_tick(v):
    if abs(v) >= 100 or v == int(v):
        return f"{v:,.0f}"
    return f"{v:,.1f}".rstrip("0").rstrip(".")


def nice_ticks(lo, hi, count=4):
    """Round axis ticks covering [lo, hi]."""
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


def x_ticks(start_ts, n_buckets, every_hours=3):
    """[(ts, 'HH:MM')] on whole IST hours divisible by every_hours."""
    end_ts = start_ts + n_buckets * BUCKET_MS
    t = datetime.fromtimestamp(start_ts / 1000, REPORT_TZ).replace(minute=0, second=0, microsecond=0).timestamp() * 1000
    ticks = []
    while t <= end_ts:
        dt = datetime.fromtimestamp(t / 1000, REPORT_TZ)
        if t >= start_ts and dt.hour % every_hours == 0:
            ticks.append((t, dt.strftime("%H:%M")))
        t += 3600 * 1000
    return ticks


def no_data(msg=NO_DATA_TEXT):
    return (f'<div style="padding:28px;text-align:center;color:{INK_MUTED};font-size:12px;background:#fafafa;'
            f'border:1px dashed {GRID};border-radius:6px;">{escape(msg)}</div>')


def svg_line_chart(series, start_ts, width=900, height=210):
    """series: list of (label, color, values per bucket with None for gaps)."""
    all_vals = [v for _, _, vals in series for v in vals if v is not None]
    if not all_vals:
        return no_data()
    n = max(len(vals) for _, _, vals in series)
    ml, mr, mt, mb = 60, 14, 10, 28
    pw, ph = width - ml - mr, height - mt - mb
    yt = nice_ticks(min(all_vals), max(all_vals))
    y0, y1 = yt[0], yt[-1]

    def xs(i):
        return ml + (i + 0.5) / n * pw

    def ys(v):
        return mt + ph - (v - y0) / (y1 - y0) * ph

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
             f'style="display:block;font-family:Arial,sans-serif;">']
    for t in yt:
        y = ys(t)
        parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 6}" y="{y + 4.5:.1f}" text-anchor="end" font-size="13" fill="{INK_MUTED}">{fmt_tick(t)}</text>')
    parts.append(f'<line x1="{ml}" x2="{width - mr}" y1="{mt + ph}" y2="{mt + ph}" stroke="{AXIS}" stroke-width="1"/>')
    for ts, label in x_ticks(start_ts, n):
        x = ml + (ts - start_ts) / (n * BUCKET_MS) * pw
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
            parts.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2" '
                         f'stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append("</svg>")
    return "".join(parts)


def series_stats_text(vals, unit):
    vs = [v for v in vals if v is not None]
    if not vs:
        return "no data"
    return f"avg {fmt_tick(sum(vs) / len(vs))} · min {fmt_tick(min(vs))} · max {fmt_tick(max(vs))} {escape(unit)}"


def chart_card(title, unit, series, start_ts, width=900, height=210):
    legend = ""
    for label, color, vals in series:
        swatch = (f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{color};'
                  f'margin-right:5px;vertical-align:-1px;"></span>') if len(series) > 1 else ""
        name = f'<b style="color:{INK};">{escape(label)}</b> ' if len(series) > 1 else ""
        legend += f'<span style="margin-right:16px;white-space:nowrap;">{swatch}{name}{series_stats_text(vals, unit)}</span>'
    return f"""
    <div style="page-break-inside:avoid;break-inside:avoid;border:1px solid #e0e0e0;border-radius:6px;padding:12px 14px 8px;margin-bottom:14px;background:#fcfcfb;">
        <div style="font-size:13px;font-weight:bold;color:{INK};">{escape(title)} <span style="font-weight:normal;color:{INK_MUTED};">({escape(unit)} · 30-min average)</span></div>
        <div style="font-size:11px;color:{INK_2};margin:6px 0 8px;line-height:1.7;">{legend}</div>
        {svg_line_chart(series, start_ts, width, height)}
    </div>
    """
