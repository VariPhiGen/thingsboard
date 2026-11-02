"""Period model: combines daily rollups (1-31 IST days) into per-equipment totals, daily rows, alarms,
maintenance history and the current maintenance outlook. Rendering lives in render_pdf / render_xlsx."""
import json
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta

from infra_reports.config import REPORT_TZ

MAX_DAYS = 31
CATEGORIES = OrderedDict([("dg", "DG Sets"), ("lt", "LT Panels"), ("ro", "RO Plant"), ("fire", "Fire Suppression")])
# Live values read at generation time for the maintenance outlook
OUTLOOK_KEYS = ["pm_health_score", "pm_severity", "pm_top_issue", "pm_recommendation", "pm_service_due_h",
                "pm_days_since_run", "pm_rul_days", "run_hours", "fuel_level_pct", "fuel_status", "fuel_runtime_h",
                "maintenance_record"]
SEVERITY_ORDER = {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2, "WARNING": 3, "INDETERMINATE": 4}


class PeriodError(ValueError):
    """Invalid period requested."""


def resolve_period(start, end, today=None):
    """Validated (start_date, end_date) for an inclusive IST date range of at most MAX_DAYS days."""
    today = today or datetime.now(REPORT_TZ).date()
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise PeriodError("Dates must be YYYY-MM-DD")
    if e < s:
        raise PeriodError("End date is before start date")
    if e > today:
        raise PeriodError("End date is in the future")
    if (e - s).days + 1 > MAX_DAYS:
        raise PeriodError(f"A report covers at most {MAX_DAYS} days")
    return s, e


def days_between(s, e):
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def period_label(s, e):
    n = (e - s).days + 1
    if n == 1:
        return "Daily"
    if n == 7:
        return "Weekly"
    last = (e.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if s.day == 1 and e == last:
        return "Monthly"
    return "Custom"


def _wavg(pairs):
    """Weighted average of (value, weight) pairs."""
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _stat_merge(day_stats):
    """Merge daily {'avg','min','max','count'} dicts."""
    day_stats = [s for s in day_stats if s]
    if not day_stats:
        return None
    return {"avg": _wavg([(s["avg"], s["count"]) for s in day_stats]),
            "min": min(s["min"] for s in day_stats), "max": max(s["max"] for s in day_stats),
            "count": sum(s["count"] for s in day_stats)}


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def build_period(rollups, categories=None, outlook=None, generated_by=None, now=None, maintenance_live=None):
    """rollups: daily rollup dicts in date order. categories: subset of CATEGORIES keys (None = all).
    outlook: {device_id: {key: (ts, value)}} live values for the maintenance outlook.
    maintenance_live: {device_id: [{'ts', 'value'}]} maintenance records read at generation time. Records can be
    logged after the day (rollups are stored once), so these replace the rollups' copies when given."""
    categories = [c for c in CATEGORIES if not categories or c in categories]
    now = now or datetime.now(REPORT_TZ)
    s = date.fromisoformat(rollups[0]["date"])
    e = date.fromisoformat(rollups[-1]["date"])
    partial = [r["date"] for r in rollups if not r.get("final")]

    devices = OrderedDict()
    for r in rollups:
        for d in r["devices"]:
            if d["category"] not in categories:
                continue
            dev = devices.setdefault(d["id"], {"id": d["id"], "name": d["name"], "category": d["category"], "days": []})
            dev["name"] = d["name"]
            dev["days"].append({"date": r["date"], **d})
    order = {c: i for i, c in enumerate(categories)}
    devs = sorted(devices.values(), key=lambda x: (order[x["category"]], x["name"].lower()))

    alarms, events, maintenance = [], [], []
    for dev in devs:
        days = dev["days"]
        dev["availability_pct"] = _wavg([(d["availability_pct"], 1) for d in days])
        dev["alarms"] = sorted((dict(a, device=dev["name"]) for d in days for a in d["alarms"]),
                               key=lambda a: a.get("start_ts") or 0)
        dev["alarms_excluded"] = sum(n for d in days for n in d.get("alarms_excluded", {}).values())
        pm_days = [d["pm"] for d in days if d.get("pm")]
        dev["pm"] = {
            "health_avg": _wavg([(p["health_avg"], 1) for p in pm_days]),
            "health_min": min((p["health_min"] for p in pm_days if p["health_min"] is not None), default=None),
            "warning_min": sum(p["warning_min"] for p in pm_days),
            "critical_min": sum(p["critical_min"] for p in pm_days),
            "issues": [t for t, _ in Counter(t for p in pm_days for t in p["top_issues"]).most_common(3)],
        } if pm_days else None
        cat = dev["category"]
        if cat == "dg":
            fuels = [d.get("fuel") for d in days]
            dev["totals"] = {
                "runs": sum(d.get("runs") or 0 for d in days),
                "run_hours": _sum(d.get("run_hours") for d in days),
                "energy_kwh": _sum(d.get("energy_kwh") for d in days),
                "fuel_consumed_pct": _sum(f and f.get("consumed_pct") for f in fuels),
                "fuel_lower_bound": any(f and f.get("lower_bound") for f in fuels),
                "refuelled_pct": _sum(f and f.get("refuelled_pct") for f in fuels),
                "refuels": sum((f or {}).get("refuel_count") or 0 for f in fuels),
                "fuel_min": min((f["min"] for f in fuels if f), default=None),
                "run_hours_end": next((d.get("run_hours_total") for d in reversed(days) if d.get("run_hours_total")), None),
            }
            for k in ("battery_voltage", "coolant_temp", "oil_pressure", "power_kw"):
                dev["totals"][k] = _stat_merge([d["stats"].get(k) for d in days])
            for d in days:
                for ev in d.get("fuel_events", []):
                    events.append({"ts": ev["ts"], "device": dev["name"], "kind": "Fuel",
                                   "text": str(ev["value"]).replace(">=", "≥")})
        elif cat == "lt":
            feeders = OrderedDict()
            for d in days:
                for key, f in d.get("feeders", {}).items():
                    agg = feeders.setdefault(key, {"label": f["label"], "days": []})
                    agg["days"].append(dict(f, date=d["date"]))
            for key, f in feeders.items():
                fd = f["days"]
                f.update({m: _stat_merge([x.get(m) for x in fd]) for m in ("voltage", "current", "power", "frequency")})
                f["energy_kwh"] = _sum(x.get("energy_kwh") for x in fd)
                f["coverage_pct"] = _wavg([(x.get("coverage_pct"), 1) for x in fd])
                if f["voltage"] and f["power"] and f["current"]:
                    v, i = f["voltage"]["avg"], f["current"]["avg"]
                    kva = (1.732 * v * i if v > 300 else v * i) / 1000 if v and i else 0
                    f["pf_avg"] = min(1.0, abs(f["power"]["avg"]) / kva) if kva > 1 else None
            dev["feeders"] = feeders
        elif cat == "ro":
            dev["totals"] = {k: _stat_merge([d["stats"].get(k) for d in days])
                             for k in ("tds_ppm", "ec_us_cm", "temperature_c", "ph", "pressure", "water_flow")}
        elif cat == "fire":
            chans = OrderedDict()
            for d in days:
                for n, c in sorted(d.get("channels", {}).items(), key=lambda kv: int(kv[0])):
                    agg = chans.setdefault(n, {"days": []})
                    agg["days"].append(dict(c, date=d["date"]))
            for n, c in chans.items():
                c["ok_pct"] = _wavg([(x["ok_pct"], x["samples"]) for x in c["days"]])
                c["changes"] = sum(x["changes"] for x in c["days"])
                c["last"] = c["days"][-1]["last"]
                c["low_days"] = sum(1 for x in c["days"] if x["ok_pct"] < 100)
            dev["channels"] = OrderedDict(sorted(chans.items(), key=lambda kv: int(kv[0])))
        recs = (maintenance_live.get(dev["id"], []) if maintenance_live is not None
                else [m for d in days for m in d.get("maintenance", [])])
        for m in recs:
            rec = m["value"] if isinstance(m["value"], dict) else {"description": str(m["value"])}
            maintenance.append({"ts": m["ts"], "device": dev["name"], **rec})
        for d in days:
            if d.get("pm") and (d["pm"]["critical_min"] or d["pm"]["warning_min"]):
                p = d["pm"]
                sev = "CRITICAL" if p["critical_min"] else "WARNING"
                mins = p["critical_min"] or p["warning_min"]
                day_start = int(datetime.fromisoformat(d["date"]).replace(tzinfo=REPORT_TZ).timestamp() * 1000)
                events.append({"ts": day_start, "device": dev["name"], "kind": "Predictive",
                               "text": f"{sev} for {mins // 60} h {mins % 60:02d} min"
                                       + (f": {'; '.join(p['top_issues'][:2])}" if p["top_issues"] else "")})
        alarms += dev["alarms"]
        dev["outlook"] = _outlook(dev, (outlook or {}).get(dev["id"], {}))

    alarms.sort(key=lambda a: a.get("start_ts") or 0)
    maintenance.sort(key=lambda m: m["ts"])
    events.sort(key=lambda x: x["ts"])
    return {
        "start": s, "end": e, "days": days_between(s, e), "label": period_label(s, e), "partial_days": partial,
        "categories": categories, "devices": devs, "alarms": alarms, "events": events, "maintenance": maintenance,
        "generated_at": now, "generated_by": generated_by,
    }


def _outlook(dev, live):
    def v(k):
        x = live.get(k)
        return x[1] if x else None

    def num(k):
        try:
            return float(v(k))
        except (TypeError, ValueError):
            return None
    last = live.get("maintenance_record")
    last_rec = None
    if last:
        try:
            last_rec = dict(json.loads(last[1]) if isinstance(last[1], str) else last[1], ts=last[0])
        except (ValueError, TypeError):
            last_rec = {"description": str(last[1]), "ts": last[0]}
    return {
        "health": num("pm_health_score"), "severity": v("pm_severity"), "top_issue": v("pm_top_issue"),
        "recommendation": v("pm_recommendation"), "service_due_h": num("pm_service_due_h"),
        "days_since_run": num("pm_days_since_run"), "rul_days": num("pm_rul_days"),
        "run_hours": num("run_hours"), "fuel_pct": num("fuel_level_pct"), "fuel_status": v("fuel_status"),
        "fuel_runtime_h": num("fuel_runtime_h"), "last_maintenance": last_rec,
    }


def fetch_outlook(client, devices):
    """{device_id: {key: (ts, value)}} of the live outlook keys."""
    out = {}
    for d in devices:
        keys = [k for k in OUTLOOK_KEYS if k in set(client.timeseries_keys(d["id"]))]
        out[d["id"]] = client.latest(d["id"], keys) if keys else {}
    return out
