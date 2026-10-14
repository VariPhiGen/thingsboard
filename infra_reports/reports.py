"""HTML for the four infrastructure PDF reports."""
from html import escape

from .charts import INK, INK_MUTED, SERIES_COLORS, chart_card, no_data, svg_status_strip
from .collect import LT_PANELS, period_of
from .layout import (
    BADGE_COLORS, alarm_section, badge, fmt_latest, fmt_sync, fmt_val, is_fresh, is_historical, kpi, kv,
    live_val, live_word, report_meta, report_page, trends_section, valid_float,
)

# Meter increase vs integrated power differing by more than this factor is flagged in the report
METER_MISMATCH_RATIO = 1.25
LOW_COVERAGE = 0.9


def _devices(summary, category):
    return sorted((d for d in summary if d.get("category") == category), key=lambda d: d["name"])


def _single(summary, category):
    devices = _devices(summary, category)
    return devices[0] if devices else None


def _period_start(summary):
    return period_of(summary)[0]


# ==============================================================================
# 1. DG SETS
# ==============================================================================
def _meter_check(meter_delta, energy_kwh):
    """Warning text when the controller kWh meter disagrees with integrated power."""
    if meter_delta is None or energy_kwh is None or max(meter_delta, energy_kwh) < 10:
        return ""
    ratio = (meter_delta + 1e-9) / (energy_kwh + 1e-9)
    if ratio > METER_MISMATCH_RATIO or ratio < 1 / METER_MISMATCH_RATIO:
        return f' <span class="warn nw">({ratio:.1f}x of power)</span>'
    return ""


def generate_dg_set_html(devices_summary):
    dg_devices = _devices(devices_summary, "dg")
    historical = is_historical(devices_summary)
    total_dg = len(dg_devices)
    active_dg = sum(1 for d in dg_devices if d["is_active"])
    running_dg = sum(1 for d in dg_devices
                     if live_val(d, "dg_status") == "RUNNING" or (valid_float(live_val(d, "engine_rpm")) or 0) > 100)
    total_alarms = sum(d["alarms_count"] for d in dg_devices)
    energy_24h = sum(d.get("energy_24h_kwh") or 0 for d in dg_devices)
    coverages = [d["energy_coverage"] for d in dg_devices if d.get("energy_coverage") is not None]
    coverage = min(coverages) if coverages else 0.0
    any_mismatch = False

    rows_html = ""
    for d in dg_devices:
        agg = d["agg_24h"]
        online = badge("ONLINE", "green") if d["is_active"] else badge("OFFLINE", "red")
        dg_state = live_val(d, "dg_status")
        state_badge = badge(dg_state, "teal" if dg_state == "RUNNING" else "grey") if dg_state else badge("NO DATA", "grey")
        meter_delta = agg.get("energy_kwh_24h_delta")
        mismatch = _meter_check(meter_delta, d.get("energy_24h_kwh"))
        any_mismatch = any_mismatch or bool(mismatch)

        rows_html += f"""
        <tr>
            <td><div class="name" style="color:#0d47a1;">{escape(d['name'])}</div><div style="margin-top:5px;">{online}</div></td>
            <td class="c">{state_badge}</td>
            <td>
                {kv(f"{live_word(devices_summary)} Power", fmt_latest(d, 'power_kw', "kW"))}
                {kv("24h Peak", fmt_val(agg.get('power_kw_24h_max'), "kW"))}
                {kv("24h Energy", fmt_val(d.get('energy_24h_kwh'), "kWh", 0))}
                {kv("Meter Change", fmt_val(meter_delta, "kWh", 0) + mismatch)}
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
            <td class="muted">{fmt_sync(d['last_activity'])}</td>
        </tr>
        """

    coverage_note = f"{coverage * 100:.0f}% data coverage" if dg_devices else ""
    kpis_html = (
        kpi(total_dg, "Total DG Sets", "#0d47a1")
        + kpi(active_dg, "Active / Online", "#2e7d32")
        + kpi(running_dg, "Currently Running", "#00796b")
        + kpi(f"{energy_24h:,.1f} kWh", "24h Energy Generated", "#ef6c00",
              f'<span class="{"warn" if coverage < LOW_COVERAGE else ""}">{coverage_note}</span>')
        + kpi(f"{total_alarms:,}", "Alarms Raised" if historical else "Active Alarms",
              "#c62828" if total_alarms > 0 else "#2e7d32")
    )

    start_ts = _period_start(devices_summary)
    dg_charts = [
        chart_card(title, unit,
                   [(d["name"], SERIES_COLORS[i % len(SERIES_COLORS)], d["series_24h"].get(key, [])) for i, d in enumerate(dg_devices)],
                   start_ts, height=180)
        for title, key, unit in [("Power Output", "power_kw", "kW"), ("Fuel Level", "fuel_level", "%"),
                                 ("Battery Voltage", "battery_voltage", "V"), ("Coolant Temperature", "coolant_temp", "°C")]
    ] if dg_devices else [no_data("No DG Set devices found")]

    mismatch_note = (" Readings marked in orange differ from the power-based energy by more than "
                     f"{METER_MISMATCH_RATIO:.2f}x; check the controller meter scaling.") if any_mismatch else ""
    body_html = f"""
    <div class="section">
        <h3>DG Sets Detailed 24h Operational Breakdown</h3>
        <table class="data">
            <thead>
                <tr style="background-color:#e3f2fd; border-bottom:2px solid #bbdefb;">
                    <th style="width:12%;">DG Set</th>
                    <th class="c" style="width:12%;">State</th>
                    <th style="width:23%;">Power &amp; Energy</th>
                    <th style="width:20%;">Fuel &amp; Battery</th>
                    <th style="width:22%;">Engine Health</th>
                    <th style="width:11%;">Last Sync</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="muted" style="margin-top:8px;">24h Energy is calculated from the power readings (kW over time).
        Meter Change is the increase of the controller's kWh counter over the same period.{mismatch_note}</div>
    </div>
    {alarm_section(dg_devices, historical)}
    {trends_section(dg_charts)}
    """

    return report_page(
        "Daily 24-Hour DG Sets Operations Report",
        "Daily 24-Hour Diesel Generator (DG Set) Operations Report",
        "linear-gradient(135deg, #0d47a1 0%, #1976d2 100%)",
        report_meta(devices_summary), kpis_html, body_html,
        "Automated DG Set 24h Operations PDF Report",
    )


# ==============================================================================
# 2. LT PANELS
# ==============================================================================
def generate_lt_panels_html(devices_summary):
    lt_master = _single(devices_summary, "lt")
    tel = lt_master["telemetry"] if lt_master else {}
    agg = lt_master["agg_24h"] if lt_master else {}
    is_active = lt_master["is_active"] if lt_master else False
    word = live_word(devices_summary)

    def energized(prefix):
        return (valid_float(live_val(lt_master, f"{prefix}_voltage")) or 0) > 0

    total_panels = len(LT_PANELS)
    active_panels = sum(1 for _, prefix in LT_PANELS if energized(prefix))
    total_kw = sum(valid_float(live_val(lt_master, f"{prefix}_power")) or 0 for _, prefix in LT_PANELS)
    live_freqs = [f for _, prefix in LT_PANELS if energized(prefix)
                  for f in [valid_float(live_val(lt_master, f"{prefix}_frequency"))] if f and 40 <= f <= 70]
    grid_freq = f"{sum(live_freqs) / len(live_freqs):.2f} Hz" if live_freqs else "N/A"

    rows_html = ""
    for name, prefix in LT_PANELS:
        if energized(prefix):
            state = badge("ENERGIZED", "green")
        elif not is_fresh(lt_master, f"{prefix}_voltage"):
            state = badge("NO LIVE DATA", "grey")
        elif valid_float(tel.get(f"{prefix}_voltage")) is None:
            state = badge("NO DATA", "grey")
        else:
            state = badge("STANDBY", "amber")

        rows_html += f"""
        <tr>
            <td class="name" style="color:#2e7d32;">{escape(name)}</td>
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

    if lt_master is None:
        master_badge = badge("DEVICE NOT FOUND", "grey")
    else:
        master_badge = badge("MASTER ONLINE", "green") if is_active else badge("MASTER OFFLINE", "red")
    kpis_html = (
        kpi(total_panels, "Sub-Panels Monitored", "#1b5e20")
        + kpi(active_panels, "Circuits Energized", "#2e7d32")
        + kpi(f"{total_kw:,.1f} kW", f"Total {word} Power Load", "#2e7d32")
        + kpi(grid_freq, f"Avg Grid Frequency ({word})", "#00796b")
    )

    lt_series = lt_master["series_24h"] if lt_master else {}
    start_ts = _period_start(devices_summary)
    lt_cards = [
        f'<div style="width:49%;">{chart_card(name, "kW", [(name, SERIES_COLORS[0], lt_series.get(f"{prefix}_power", []))], start_ts, width=440, height=170)}</div>'
        for name, prefix in LT_PANELS
    ]
    # Two charts per row; each row stays on one page
    lt_charts = [
        f'<div style="display:flex;justify-content:space-between;page-break-inside:avoid;break-inside:avoid;">{"".join(lt_cards[i:i + 2])}</div>'
        for i in range(0, len(lt_cards), 2)
    ]

    body_html = f"""
    <div class="section">
        <h3>LT Sub-Panels Electrical Readings <span class="sub">({word} values + 24h statistics)</span></h3>
        <table class="data">
            <thead>
                <tr style="background-color:#e8f5e9; border-bottom:2px solid #c8e6c9;">
                    <th style="width:14%;">Sub-Panel</th>
                    <th class="c" style="width:15%;">State</th>
                    <th class="r" style="width:14%;">{word} Power</th>
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
    {alarm_section([lt_master], is_historical(devices_summary)) if lt_master else ""}
    {trends_section(lt_charts)}
    """

    return report_page(
        "Daily 24-Hour LT Panels Electrical Load Report",
        "Daily 24-Hour Low Voltage (LT) Panels Electrical Report",
        "linear-gradient(135deg, #1b5e20 0%, #388e3c 100%)",
        report_meta(devices_summary, f" &nbsp;|&nbsp; Status: {master_badge}"), kpis_html, body_html,
        "Automated LT Panels 24h Electrical PDF Report",
    )


# ==============================================================================
# 3. FIRE SUPPRESSION
# ==============================================================================
def generate_fire_suppression_html(devices_summary):
    fire_dev = _single(devices_summary, "fire")
    tel = fire_dev["telemetry"] if fire_dev else {}
    agg = fire_dev["agg_24h"] if fire_dev else {}
    alarms_count = fire_dev["alarms_count"] if fire_dev else 0
    historical = is_historical(devices_summary)

    def flag(key):
        """True/False from a boolean telemetry key, None when not reported in the period."""
        v = live_val(fire_dev, key)
        return None if v is None else str(v).lower() == "true"

    relay_online = flag("relay_online")
    low_press_ok = flag("low_pressure")
    high_press_ok = flag("high_pressure")
    cyl_statuses = [flag(f"cylinder_pressure_{i}") for i in range(1, 10)]
    cyl_reported = [s for s in cyl_statuses if s is not None]
    cyl_ok_count = sum(1 for s in cyl_reported if s)
    cyl_all_ok = bool(cyl_reported) and cyl_ok_count == len(cyl_reported)

    has_data = bool(cyl_reported) or relay_online is not None
    if alarms_count:
        sys_status_badge = badge(f"{alarms_count:,} ALARM(S) {'RAISED' if historical else 'ACTIVE'}", "red")
    elif not has_data:
        sys_status_badge = badge("NO DATA IN PERIOD", "grey")
    else:
        sys_status_badge = badge("SYSTEM NORMAL", "green")

    def state_kpi(ok, ok_text, bad_text, label):
        if ok is None:
            return kpi("NO DATA", label, "#9ca3af")
        return kpi(ok_text if ok else bad_text, label, "#2e7d32" if ok else "#c62828")

    if not cyl_reported:
        cyl_kpi = kpi("NO DATA", "Cylinders Pressure", "#9ca3af")
    else:
        cyl_color = "#2e7d32" if cyl_all_ok and len(cyl_reported) == 9 else "#c62828" if cyl_ok_count < len(cyl_reported) else "#ef6c00"
        cyl_kpi = kpi(f"{cyl_ok_count} / 9 OK", "Cylinders Pressure", cyl_color)
    kpis_html = (
        state_kpi(relay_online, "ONLINE", "OFFLINE", "Relay Gateway State")
        + state_kpi(low_press_ok, "NORMAL", "LOW", "Low Pressure Line")
        + state_kpi(high_press_ok, "NORMAL", "HIGH ALARM", "High Pressure Line")
        + cyl_kpi
    )

    rows_html = ""
    for i in range(1, 10):
        cyl = cyl_statuses[i - 1]
        di = flag(f"di{i}")
        cyl_badge = badge("NO DATA", "grey") if cyl is None else badge("PRESSURE OK", "green") if cyl else badge("PRESSURE LOW", "red")
        if di is None:
            di_badge = badge("NO DATA", "grey") if f"di{i}" in tel else badge("NOT REPORTED", "grey")
        else:
            di_badge = badge("CLOSED / NORMAL", "green") if di else badge("OPEN / CHECK", "amber")

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

    fire_series = fire_dev["series_24h"] if fire_dev else {}
    fire_rows = [("Relay Gateway Online", fire_series.get("relay_online", []))] + [
        (f"Cylinder {i} Pressure", fire_series.get(f"cylinder_pressure_{i}", [])) for i in range(1, 10)
    ]
    fire_charts = f"""
    <div style="page-break-inside:avoid;break-inside:avoid;border:1px solid #e0e0e0;border-radius:6px;padding:12px 14px;background:#fcfcfb;">
        <div style="font-size:13px;font-weight:bold;color:{INK};">Safety Signal Status Timeline <span style="font-weight:normal;color:{INK_MUTED};">(30-min buckets)</span></div>
        {svg_status_strip(fire_rows, _period_start(devices_summary))}
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
    {alarm_section([fire_dev], historical) if fire_dev else ""}
    {trends_section(fire_charts)}
    """

    return report_page(
        "Daily 24-Hour Fire Suppression Safety Report",
        "Daily 24-Hour Fire Suppression Safety Report",
        "linear-gradient(135deg, #b71c1c 0%, #c62828 100%)",
        report_meta(devices_summary, f" &nbsp;|&nbsp; Overall Status: {sys_status_badge}"), kpis_html, body_html,
        "Automated Fire Suppression 24h Safety PDF Report",
    )


# ==============================================================================
# 4. RO PLANT
# ==============================================================================
def _compliance(text, color):
    return f'<b style="color:{BADGE_COLORS[color]};">{text}</b>'


def tds_compliance(tds):
    if tds is None:
        return _compliance("No Data", "grey"), "No Data"
    if tds < 200:
        return _compliance("Optimal (&lt; 200 ppm)", "green"), "Optimal (&lt; 200 ppm)"
    if tds <= 500:
        return _compliance("Acceptable (200-500 ppm)", "amber"), "Acceptable (200-500 ppm)"
    return _compliance("High (&gt; 500 ppm)", "red"), "High (&gt; 500 ppm)"


def ph_compliance(ph):
    if ph is None:
        return _compliance("No Data", "grey"), "No Data"
    if 6.5 <= ph <= 8.5:
        return _compliance("Balanced (6.5 - 8.5)", "green"), "Balanced (6.5 - 8.5)"
    return _compliance("Out of Range (6.5 - 8.5)", "red"), "Out of Range (6.5 - 8.5)"


def generate_ro_plant_html(devices_summary):
    ro_dev = _single(devices_summary, "ro")
    tel = ro_dev["telemetry"] if ro_dev else {}
    agg = ro_dev["agg_24h"] if ro_dev else {}
    last_data = ro_dev["last_activity"] if ro_dev else "No activity"

    tds, flow, ph = valid_float(tel.get("tds")), valid_float(tel.get("water_flow")), valid_float(tel.get("ph"))
    flow_c = ((_compliance("No Data", "grey"), "No Data") if flow is None
              else (_compliance("Normal Flow", "green"), "Normal Flow") if flow > 0
              else (_compliance("No Flow", "amber"), "No Flow"))
    press_c = ((_compliance("No Data", "grey"), "No Data") if valid_float(tel.get("pressure")) is None
               else (_compliance("Monitored", "blue"), "Monitored"))

    def param_row(label, key, unit, comp, decimals=1):
        comp_html, comp_text = comp
        if ro_dev and key in tel and not is_fresh(ro_dev, key):
            comp_html = f'<span class="na">Last known: {comp_text}</span>'
        return f"""
        <tr>
            <td class="name" style="color:#0369a1;">{label}</td>
            <td class="r"><b>{fmt_latest(ro_dev, key, unit, decimals)}</b></td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_avg"), unit, decimals)}</td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_min"), unit, decimals)}</td>
            <td class="r">{fmt_val(agg.get(f"{key}_24h_max"), unit, decimals)}</td>
            <td>{comp_html}</td>
        </tr>
        """

    rows_html = (
        param_row("TDS (Total Dissolved Solids)", "tds", "ppm", tds_compliance(tds), 0)
        + param_row("Permeate Water Flow Rate", "water_flow", "L/min", flow_c)
        + param_row("RO Membrane Pressure", "pressure", "psi", press_c)
        + param_row("pH Level", "ph", "", ph_compliance(ph))
    )

    kpis_html = (
        kpi(fmt_latest(ro_dev, "tds", "ppm", 0), "Latest TDS Level", "#0288d1")
        + kpi(fmt_val(agg.get("tds_24h_avg"), "ppm", 0), "24h Avg TDS", "#039be5")
        + kpi(fmt_latest(ro_dev, "water_flow", "L/min"), "Permeate Water Flow", "#00796b")
        + kpi(fmt_latest(ro_dev, "pressure", "psi"), "RO Pressure", "#2e7d32")
    )

    ro_series = ro_dev["series_24h"] if ro_dev else {}
    start_ts = _period_start(devices_summary)
    if any(v is not None for vals in ro_series.values() for v in vals):
        ro_charts = [
            chart_card(title, unit, [(title, SERIES_COLORS[0], ro_series.get(key, []))], start_ts)
            for title, key, unit in [("TDS", "tds", "ppm"), ("Permeate Water Flow", "water_flow", "L/min"),
                                     ("RO Membrane Pressure", "pressure", "psi"), ("pH Level", "ph", "pH")]
        ]
    else:
        ro_charts = [no_data()]

    if ro_dev is None:
        status_badge = badge("DEVICE NOT FOUND", "grey")
    elif is_fresh(ro_dev, "status"):
        status_badge = badge(tel.get("status"), "blue")
    else:
        status_badge = badge("NO DATA IN PERIOD", "grey")

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
        <div class="muted" style="margin-top:8px;">Greyed readings with an "as of" date were not updated during the report period (device last activity: {escape(last_data)}). Compliance is evaluated on the latest reading.</div>
    </div>
    {alarm_section([ro_dev], is_historical(devices_summary)) if ro_dev else ""}
    {trends_section(ro_charts)}
    """

    return report_page(
        "Daily 24-Hour RO Plant Water Quality Report",
        "Daily 24-Hour RO Plant Water Quality &amp; Treatment Report",
        "linear-gradient(135deg, #0288d1 0%, #039be5 100%)",
        report_meta(devices_summary, f" &nbsp;|&nbsp; Status: {status_badge}"), kpis_html, body_html,
        "Automated RO Plant Water Treatment 24h PDF Report",
    )


REPORTS = [
    ("dg_set", "DG Set Operations Report", "DG_Set_24h_Report", generate_dg_set_html),
    ("lt_panels", "LT Panels Power Report", "LT_Panels_24h_Report", generate_lt_panels_html),
    ("fire_suppression", "Fire Suppression Safety Report", "Fire_Suppression_24h_Report", generate_fire_suppression_html),
    ("ro_plant", "RO Plant Water Quality Report", "RO_Plant_24h_Report", generate_ro_plant_html),
]
