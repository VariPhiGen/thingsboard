"""Daily rollups: one compact JSON per IST day with every device's statistics, alarms and events.

Weekly/monthly/custom reports are built from these files, so a 31-day report does not have to fetch a
month of raw telemetry. A rollup reuses infra_reports.collect (the same numbers as the daily email PDFs)
and adds what multi-day maintenance reports need: alarm lists, DG fuel use and refuels, maintenance
records, predictive-maintenance health, LT feeder energy and fire-channel stability.

  python3 -m period_reports.rollup --date yesterday          # nightly job
  python3 -m period_reports.rollup --backfill 90             # last 90 complete days (skips existing)
"""
import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta

from infra_reports.collect import LT_PANELS, collect_summary
from infra_reports.config import REPORT_TZ, load_settings
from infra_reports.metrics import BUCKET_MS, report_window, resolve_report_date, valid_samples
from infra_reports.tb_client import ThingsBoardClient

log = logging.getLogger(__name__)

ROLLUP_VERSION = 3   # 2: refuels detected from the level; 3: offline LT meters (0 V / 0 Hz) excluded
ROLLUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports_data", "rollups")
# A day is final once it ended this long ago (late telemetry from gateways with a backlog)
FINAL_AFTER_MS = 30 * 60 * 1000
PM_EVAL_MIN = 5          # the PM engine evaluates every 5 min: one pm_severity sample = 5 min
FULL_SCALE = 99.95
# Keys fetched in addition to infra_reports.collect.HISTORY_KEYS
EXTRA_KEYS = {
    "dg": ["fuel_level", "fuel_level_pct", "fuel_event", "maintenance_record", "pm_health_score", "pm_severity", "pm_top_issue"],
    "lt": ["maintenance_record", "pm_health_score", "pm_severity", "pm_top_issue"],
    "ro": ["maintenance_record", "pm_health_score", "pm_severity", "pm_top_issue"],
    "fire": ["maintenance_record", "pm_health_score", "pm_severity", "pm_top_issue"],
}
# 30-min series kept in the rollup (hourly averages) for period charts
SERIES_KEYS = {
    "dg": ["power_kw", "fuel_level", "battery_voltage", "coolant_temp"],
    "lt": [f"{prefix}_power" for _, prefix in LT_PANELS],
    "ro": ["tds_ppm", "temperature_c"],
    "fire": [],
}
FIRE_CHANNEL = re.compile(r"^(cylinder_pressure_(\d+)|fire_suppression_(\d+)_pressure)$")
REFUEL_RE = re.compile(r"^Refuel (>= )?\+([\d.]+)%")


def _r(x, n=2):
    return None if x is None else round(x, n)


def _hourly(series):
    """30-min bucket averages -> hourly averages (None where both halves are empty)."""
    out = []
    for i in range(0, len(series), 2):
        vals = [v for v in series[i:i + 2] if v is not None]
        out.append(_r(sum(vals) / len(vals), 3) if vals else None)
    return out


def _stats(agg, key):
    s = {k: agg.get(f"{key}_24h_{k}") for k in ("avg", "min", "max", "count")}
    return {k: (_r(v, 3) if k != "count" else v) for k, v in s.items()} if s["count"] else None


def _pm(history):
    health = [v for _, v in valid_samples(history.get("pm_health_score", []))]
    sev = [str(p.get("value")) for p in history.get("pm_severity", [])]
    issues = Counter(str(p.get("value")) for p in history.get("pm_top_issue", []) if str(p.get("value")) not in ("None", ""))
    if not health and not sev:
        return None
    worst = "CRITICAL" if "CRITICAL" in sev else ("WARNING" if "WARNING" in sev else ("OK" if "OK" in sev else None))
    return {
        "health_avg": _r(sum(health) / len(health), 1) if health else None,
        "health_min": min(health) if health else None,
        "worst": worst,
        "warning_min": sev.count("WARNING") * PM_EVAL_MIN,
        "critical_min": sev.count("CRITICAL") * PM_EVAL_MIN,
        "top_issues": [t for t, _ in issues.most_common(3)],
    }


def _records(history, key):
    out = []
    for p in history.get(key, []):
        value = p.get("value")
        if key == "maintenance_record":
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                value = {"description": str(value)}
        out.append({"ts": int(p["ts"]), "value": value})
    return out


def _median_smooth(values, n=5):
    """Rolling median: removes single-sample spikes (the sender reads full scale on a loose contact)."""
    out = []
    for i in range(len(values)):
        win = sorted(values[max(0, i - n // 2):i + n // 2 + 1])
        out.append(win[len(win) // 2])
    return out


def _detect_refuels(samples, bucket_ms=10 * 60 * 1000, min_step=2.0, min_total=5.0):
    """(total %, count) of refuels found in the level itself: 10-min medians rising by >= min_step per bucket,
    a contiguous rise counting when it adds >= min_total. Used only on days without fuel_event records
    (before the DG Fuel rule node existed). A running DG only consumes, so rises are refuels."""
    buckets = {}
    for ts, v in samples:
        buckets.setdefault(ts // bucket_ms, []).append(v)
    med = [sorted(vs)[len(vs) // 2] for _, vs in sorted(buckets.items())]
    total, count, rise = 0.0, 0, 0.0
    for a, b in zip(med, med[1:]):
        if b - a >= min_step:
            rise += b - a
        else:
            if rise >= min_total:
                total, count = total + rise, count + 1
            rise = 0.0
    if rise >= min_total:
        total, count = total + rise, count + 1
    return total, count


def _dg_fuel(history, fuel_events):
    """Fuel use of the day in % of the sender span: (first - last) + refuelled. The filtered level
    (fuel_level_pct, from the DG Fuel rule node) is used when present, else the raw level smoothed.
    A day starting or ending at the sender's full scale (100) is a lower bound: fuel above it is hidden."""
    source = "fuel_level_pct" if history.get("fuel_level_pct") else "fuel_level"
    samples = [(t, v) for t, v in valid_samples(history.get(source, [])) if 0 <= v <= 100]
    if not samples:
        return None
    values = [v for _, v in samples]
    if source == "fuel_level":
        values = _median_smooth(values)
    if fuel_events:
        refuelled, count = _refuelled(fuel_events)
        refuel_source = "events"
    else:
        refuelled, count = _detect_refuels(list(zip([t for t, _ in samples], values)))
        refuel_source = "level"
    start, end = values[0], values[-1]
    return {"source": source, "min": min(values), "max": max(values), "avg": _r(sum(values) / len(values)),
            "start": start, "end": end, "consumed_pct": _r(max(0.0, start - end + refuelled), 1),
            "refuelled_pct": _r(refuelled, 1), "refuel_count": count, "refuel_source": refuel_source,
            "lower_bound": start >= FULL_SCALE or end >= FULL_SCALE}


def _refuelled(fuel_events):
    total, count = 0.0, 0
    for e in fuel_events:
        m = REFUEL_RE.match(str(e["value"]))
        if m:
            total += float(m.group(2))
            count += 1
    return total, count


def _fire_channels(history):
    out = {}
    for key, points in history.items():
        m = FIRE_CHANNEL.match(key)
        if not m:
            continue
        vals = [v for _, v in valid_samples(points)]
        if not vals:
            continue
        changes = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
        out[str(int(m.group(2) or m.group(3)))] = {"key": key, "ok_pct": _r(100.0 * sum(vals) / len(vals), 1),
                                                   "changes": changes, "last": vals[-1], "samples": len(vals)}
    return out


def _availability(series_by_key, elapsed=None):
    """Share of the elapsed 30-min buckets in which the device sent at least one valid reading."""
    buckets = None
    for series in series_by_key.values():
        has = [v is not None for v in series]
        buckets = has if buckets is None else [a or b for a, b in zip(buckets, has)]
    if not buckets:
        return 0.0
    buckets = buckets[:elapsed] if elapsed else buckets
    return _r(100.0 * sum(buckets) / len(buckets), 1) if buckets else 0.0


def build_device(client, d, start_ts, end_ts, now_ms=None):
    cat = d["category"]
    agg = d["agg_24h"]
    keys = set(client.timeseries_keys(d["id"]))
    extra = [k for k in EXTRA_KEYS.get(cat, []) if k in keys]
    if cat == "fire":
        extra += [k for k in keys if FIRE_CHANNEL.match(k)]
    history = client.history(d["id"], sorted(set(extra)), start_ts, end_ts) if extra else {}
    series = d.get("series_24h", {})
    out = {
        "id": d["id"], "name": d["name"], "type": d["type"], "category": cat,
        "online": d["is_active"],
        # An unfinished day counts only the buckets that have started
        "availability_pct": _availability(series, -(-(min(now_ms or end_ts, end_ts) - start_ts) // BUCKET_MS)),
        "alarms": d.get("alarm_list", []),
        "alarms_excluded": d.get("alarms_excluded", {}),
        "operational_events": d.get("operational_events", {}),
        "maintenance": _records(history, "maintenance_record"),
        "pm": _pm(history),
        "series": {k: _hourly(series[k]) for k in SERIES_KEYS.get(cat, []) if k in series},
        "stats": {},
    }
    if cat == "dg":
        fuel_events = _records(history, "fuel_event")
        rh = agg.get("run_hours_24h_delta")
        out.update({
            "runs": d.get("runs_24h") or 0,
            "run_hours": _r(rh, 2) if rh is not None and 0 <= rh <= 24 else None,
            "energy_kwh": _r(d.get("energy_24h_kwh"), 1),
            "energy_coverage": _r(d.get("energy_coverage"), 3),
            "fuel": _dg_fuel(history, fuel_events),
            "fuel_events": fuel_events,
            "run_hours_total": _r(agg.get("run_hours_24h_max"), 2),
        })
        for k in ("battery_voltage", "coolant_temp", "oil_pressure", "power_kw", "engine_rpm"):
            out["stats"][k] = _stats(agg, k)
    elif cat == "lt":
        feeders = {}
        for label, prefix in LT_PANELS:
            st = {m: _stats(agg, f"{prefix}_{m}") for m in ("voltage", "current", "power", "frequency")}
            if not st["voltage"]:
                continue   # meter offline (no valid voltage) for the whole day
            p = series.get(f"{prefix}_power") or []
            energy = sum(v * 0.5 for v in p if v is not None and v >= 0)   # 30-min buckets
            covered = sum(1 for v in p if v is not None)
            feeders[prefix] = {"label": label, **st, "energy_kwh": _r(energy, 1),
                               "coverage_pct": _r(100.0 * covered / len(p), 1) if p else 0.0}
        out["feeders"] = feeders
    elif cat == "ro":
        for k in ("tds_ppm", "ec_us_cm", "temperature_c", "ph", "pressure", "water_flow", "salinity_ppm"):
            out["stats"][k] = _stats(agg, k)
    elif cat == "fire":
        out["channels"] = _fire_channels(history)
        for k in ("relay_online", "relay_1_online", "relay_2_online"):
            out["stats"][k] = _stats(agg, k)
    return out


def clean_samples(category, key, samples):
    """LT meter values outside physical limits are meter glitches, not readings: an offline meter reports
    0 V / 0 Hz, and while it powers up it reports values like 24 V or 21 Hz. Kept: >= 100 V, 40-70 Hz."""
    if category == "lt" and key.endswith("_voltage"):
        return [(t, v) for t, v in samples if v >= 100]
    if category == "lt" and key.endswith("_frequency"):
        return [(t, v) for t, v in samples if 40 <= v <= 70]
    return samples


def build_rollup(client, settings, day, now_ms=None):
    """Rollup dict of the IST date 'YYYY-MM-DD'."""
    day = resolve_report_date(day)
    start_ts, end_ts = report_window(day)
    now_ms = now_ms or int(time.time() * 1000)
    summary = collect_summary(client, settings.profiles, day, sample_filter=clean_samples)
    devices = [build_device(client, d, start_ts, end_ts, now_ms) for d in summary]
    return {"version": ROLLUP_VERSION, "date": day, "start_ts": start_ts, "end_ts": end_ts,
            "final": now_ms >= end_ts + FINAL_AFTER_MS, "generated_at": now_ms, "devices": devices}


# ------------------------------------------------------------------ storage
def path_of(day):
    return os.path.join(ROLLUP_DIR, f"{day}.json")


def load(day):
    try:
        with open(path_of(day)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if data.get("version") == ROLLUP_VERSION else None


def save(rollup):
    os.makedirs(ROLLUP_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ROLLUP_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(rollup, f, separators=(",", ":"))
    os.chmod(tmp, 0o664)
    os.replace(tmp, path_of(rollup["date"]))


def get_days(days, client=None, settings=None, now_ms=None):
    """Rollups of the given IST dates. Stored final rollups are reused; missing or non-final past days are
    built and stored; today (incomplete) is built live and not stored."""
    out = []
    for day in days:
        cached = load(day)
        if cached and cached.get("final"):
            out.append(cached)
            continue
        if client is None:
            settings = settings or load_settings()
            client = ThingsBoardClient.connect(settings)
        rollup = build_rollup(client, settings or load_settings(), day, now_ms)
        if rollup["final"]:
            save(rollup)
        out.append(rollup)
    return out


def ist_today():
    return datetime.now(REPORT_TZ).date()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="IST date YYYY-MM-DD or 'yesterday' (rebuilt even if stored)")
    ap.add_argument("--backfill", type=int, help="build the last N complete days that are not stored yet")
    ap.add_argument("--alert", action="store_true", help="send a Telegram alert on failure")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    try:
        client = ThingsBoardClient.connect(settings)
        if args.date:
            rollup = build_rollup(client, settings, args.date)
            save(rollup)
            log.info("Rollup %s: %d devices (final=%s)", rollup["date"], len(rollup["devices"]), rollup["final"])
        if args.backfill:
            today = ist_today()
            for i in range(args.backfill, 0, -1):
                day = (today - timedelta(days=i)).isoformat()
                if load(day) and load(day).get("final"):
                    continue
                t0 = time.time()
                rollup = build_rollup(client, settings, day)
                save(rollup)
                log.info("Backfilled %s: %d devices in %.1fs", day, len(rollup["devices"]), time.time() - t0)
    except Exception as exc:
        log.exception("Rollup failed")
        if args.alert:
            from infra_reports.delivery import send_failure_alert
            send_failure_alert(settings, "daily rollup", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
