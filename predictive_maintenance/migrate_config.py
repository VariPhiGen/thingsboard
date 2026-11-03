"""Move every predictive-maintenance value out of the code into ThingsBoard configuration.

  python3 -m predictive_maintenance.migrate_config --dry-run
  python3 -m predictive_maintenance.migrate_config --apply --backup-dir <dir>

1. pm_config of every device whose profile is listed in pm_seed.json "profiles" becomes
   {kind, engine, limits, ...}. Values already configured on a device are kept (also the earlier flat keys such as
   fuel_low_pct, last_service_run_hours, rated_a, ignore_channels); only missing values come from the seed.
   Per-device values are derived from the device's own history using the "derive" rules of the seed
   (12 V / 24 V battery system, nominal voltage of the DG output and of each LT feeder, RO TDS warning level).
2. The template (pm_seed.json) is stored on the asset "Maintenance Settings" (attribute pm_templates) so new equipment
   can be configured from the dashboard.
3. The "Predictive Maintenance" rule chain routes by pm_config.kind instead of device-profile names:
   a "Fetch PM Config" node runs first; Route, Equipment Type and AI Summary Fields read the kind from it.
Idempotent: running it again changes nothing that is already configured.
"""
import argparse
import copy
import json
import logging
import os
import statistics
import sys
import time

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = json.load(open(os.path.join(HERE, "pm_seed.json")))
CHAIN_NAME = "Predictive Maintenance"
SETTINGS_NAME, SETTINGS_TYPE = "Maintenance Settings", "Maintenance Settings"
log = logging.getLogger("pm.migrate")

# Earlier flat pm_config keys -> location in limits (kept when a device already had them)
FLAT = {"fuel_low_pct": "fuel.low_pct", "fuel_critical_pct": "fuel.critical_pct", "fuel_tank_capacity_l": "fuel.tank_capacity_l",
        "fuel_drop_alarm_pct": "fuel.drop_alarm_pct", "fuel_refuel_detect_pct": "fuel.refuel_detect_pct",
        "required_autonomy_h": "fuel.required_autonomy_h", "service_interval_h": "service.interval_h",
        "last_service_run_hours": "service.last_service_run_hours", "exercise_days": "exercise.days", "rated_kw": "load.rated_kw",
        "rated_a": "rated_a", "nominal_v": "nominal_v", "ignore_channels": "ignore_channels", "tds_warn": "tds.warn_ppm",
        "tds_crit": "tds.crit_ppm"}

ROUTE_JS = """var cfg = {};
try { cfg = JSON.parse(metadata.ss_pm_config || '{}'); } catch (e) { cfg = {}; }
var out = [];
if (cfg.kind) out.push('PM');
var fk = cfg.limits && cfg.limits.keys ? cfg.limits.keys.fuel_raw : null;
if (cfg.kind === 'DG' && fk && msg[fk] !== undefined) out.push('FUEL');
return out;
"""
SWITCH_JS = """var cfg = {};
try { cfg = JSON.parse(metadata.ss_pm_config || '{}'); } catch (e) { cfg = {}; }
return [cfg.kind || 'Other'];
"""


def deep_fill(target, source):
    """Add keys of source that target lacks (recursively); never overwrite configured values."""
    for k, v in source.items():
        if k.startswith("_"):
            continue
        if k not in target:
            target[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            deep_fill(target[k], v)
    return target


def set_path(o, path, v):
    parts = path.split(".")
    for p in parts[:-1]:
        o = o.setdefault(p, {})
    o[parts[-1]] = v


def strip_notes(o):
    if isinstance(o, dict):
        return {k: strip_notes(v) for k, v in o.items() if not k.startswith("_")}
    return o


class Tb:
    def __init__(self, client):
        self.c = client

    def req(self, method, path, **kw):
        r = self.c.session.request(method, self.c.base_url + path, headers=self.c._headers, timeout=120, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.text else None

    def attrs(self, eid, keys, etype="DEVICE"):
        res = self.req("GET", f"/api/plugins/telemetry/{etype}/{eid}/values/attributes/SERVER_SCOPE", params={"keys": ",".join(keys)}) or []
        out = {}
        for a in res:
            v = a["value"]
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            out[a["key"]] = v
        return out

    def save(self, eid, values, etype="DEVICE"):
        body = {k: json.dumps(v) if isinstance(v, (dict, list)) else ("" if v is None else v) for k, v in values.items()}
        self.req("POST", f"/api/plugins/telemetry/{etype}/{eid}/attributes/SERVER_SCOPE", json=body)

    def history_values(self, eid, key, days):
        now = int(time.time() * 1000)
        res = self.req("GET", f"/api/plugins/telemetry/DEVICE/{eid}/values/timeseries",
                       params={"keys": key, "startTs": now - days * 86400000, "endTs": now, "limit": 50000, "agg": "NONE"}) or {}
        out = []
        for p in res.get(key, []):
            try:
                out.append(float(p["value"]))
            except (TypeError, ValueError):
                pass
        return out


def nominal_from(median, rule):
    return rule["three_phase_v"] if median > rule["three_phase_if_median_above_v"] else rule["single_phase_v"]


def fill_battery_float(limits, baseline):
    """DG battery float level = the battery's own 7-day standby median (only when not configured yet)."""
    bat = limits.setdefault("battery", {})
    bm = (baseline.get("battery_voltage") or {}).get("median")
    if bat.get("float_v") is None and bm:
        bat["float_v"] = round(float(bm), 2)
        return [f"battery float {bat['float_v']} V (7-day median)"]
    return [] if bat.get("float_v") is not None else ["battery float level not derivable (no history) - falling-trend check off until set"]


def derive(tb, device, kind, limits, baseline):
    """Per-device values from the device's own history (only where the device has no configured value yet)."""
    d, notes = SEED["derive"], []
    if kind == "DG":
        bm = (baseline.get("battery_voltage") or {}).get("median")
        if bm and bm <= d["battery_12v_if_median_at_or_below_v"]:
            for k in ("crit_v", "warn_v", "trend_floor_v", "overcharge_v", "falling_v_per_h"):
                limits["battery"][k] = round(limits["battery"][k] / 2, 3)
            notes.append(f"battery 12 V system (median {bm} V)")
        notes += fill_battery_float(limits, baseline)
        rule = d["nominal_voltage"]
        vals = [v for v in tb.history_values(device["id"], limits["keys"]["voltage"], rule["history_days"])
                if rule["min_valid_v"] <= v < SEED["engine"]["invalid_at_or_above"]]
        if vals:
            med = statistics.median(vals)
            limits["voltage"]["nominal_v"] = nominal_from(med, rule)
            notes.append(f"DG nominal {limits['voltage']['nominal_v']} V (running median {round(med, 1)} V)")
        else:
            limits["voltage"]["nominal_v"] = None
            notes.append("DG nominal voltage not derivable (no running data) - voltage check off until set")
    elif kind == "LT":
        rule, sfx = d["nominal_voltage"], limits["feeder_suffix"]["voltage"]
        for k, st in baseline.items():
            if k.endswith(sfx) and st.get("median") and st["median"] >= rule["min_valid_v"]:
                feeder = k[:-len(sfx)]
                if feeder not in limits["nominal_v"]:
                    limits["nominal_v"][feeder] = nominal_from(st["median"], rule)
        notes.append(f"LT nominal V for {len(limits['nominal_v'])} feeders")
    elif kind == "RO":
        med = (baseline.get(limits["keys"]["tds"]) or {}).get("median")
        tw = d["tds_warn"]
        if med:
            limits["tds"]["warn_ppm"] = round(min(tw["max_ppm"], max(tw["min_ppm"], med * tw["factor_of_median"])), 1)
            notes.append(f"TDS warning {limits['tds']['warn_ppm']} ppm (median {med})")
    return notes


def new_config(tb, device, kind, current):
    cur = current if isinstance(current, dict) else {}
    if isinstance(cur.get("limits"), dict) and isinstance(cur.get("engine"), dict):
        cfg = copy.deepcopy(cur)                              # already migrated: only fill new keys
        deep_fill(cfg["limits"], strip_notes(SEED["kinds"][kind]))
        deep_fill(cfg["engine"], strip_notes(SEED["engine"]))
        notes = ["already migrated - missing keys filled"]
        if kind == "DG":
            baseline = tb.attrs(device["id"], ["pm_baseline"]).get("pm_baseline") or {}
            notes += fill_battery_float(cfg["limits"], baseline)
        return cfg, notes
    limits = strip_notes(copy.deepcopy(SEED["kinds"][kind]))
    baseline = tb.attrs(device["id"], ["pm_baseline"]).get("pm_baseline") or {}
    notes = derive(tb, device, kind, limits, baseline)
    kept = []
    for flat, path in FLAT.items():
        if flat in cur and cur[flat] not in (None, "", {}, []):
            set_path(limits, path, copy.deepcopy(cur[flat]))
            kept.append(flat)
    if kept:
        notes.append("kept configured: " + ", ".join(kept))
    cfg = {k: v for k, v in cur.items() if k not in FLAT}   # unknown extra keys stay
    cfg.update(kind=kind, engine=strip_notes(copy.deepcopy(SEED["engine"])), limits=limits)
    return cfg, notes


def migrate_chain(tb, chain_id, ai_out_js, apply):
    md = tb.req("GET", f"/api/ruleChain/{chain_id}/metadata")
    names = {n["name"]: i for i, n in enumerate(md["nodes"])}
    changes = []
    if "Fetch PM Config" not in names:
        md["nodes"].append({"type": "org.thingsboard.rule.engine.metadata.TbGetAttributesNode", "name": "Fetch PM Config",
                            "configuration": {"fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [],
                                              "serverAttributeNames": ["pm_config"], "latestTsKeyNames": [],
                                              "tellFailureIfAbsent": False, "getLatestValueWithTs": False},
                            "configurationVersion": 1, "debugSettings": {"failuresEnabled": True, "allEnabled": False, "allEnabledUntil": 0},
                            "singletonMode": False, "queueName": None, "additionalInfo": {"layoutX": 120, "layoutY": 520, "description": ""}})
        new = len(md["nodes"]) - 1
        md["connections"].append({"fromIndex": new, "toIndex": names["Route"], "type": "Success"})
        md["firstNodeIndex"] = new
        changes.append("added Fetch PM Config as first node")
    for node, js in (("Route", ROUTE_JS), ("Equipment Type", SWITCH_JS), ("AI Summary Fields", ai_out_js)):
        c = md["nodes"][names[node]]["configuration"]
        if c.get("jsScript") != js:
            c["jsScript"] = js
            changes.append(f"{node} reads pm_config.kind")
    win = SEED["kinds"]["FIRE"]["window_minutes"]
    fire = md["nodes"][names["Fire Channels Last 15 min"]]["configuration"]
    if fire.get("startInterval") != win:
        fire["startInterval"] = win
        changes.append(f"fire channel window {win} min")
    if changes and apply:
        tb.req("POST", "/api/ruleChain/metadata", json=md)
    return changes


def main(argv=None):
    ap = argparse.ArgumentParser(description="Move predictive-maintenance values into ThingsBoard configuration")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir", help="where the previous pm_config values and rule chain are saved (required with --apply)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.apply and not args.backup_dir:
        ap.error("--backup-dir is required with --apply")
    from predictive_maintenance.deploy_pm import LLM_OUT_JS
    tb = Tb(ThingsBoardClient.connect(load_settings()))
    devices = []
    for profile, kind in SEED["profiles"].items():
        res = tb.req("GET", "/api/tenant/devices", params={"pageSize": 500, "page": 0, "type": profile})
        devices += [{"id": d["id"]["id"], "name": d["name"], "profile": profile, "kind": kind} for d in res["data"]]
    backup = {"ts": int(time.time() * 1000), "devices": {}}
    for d in devices:
        cur = tb.attrs(d["id"], ["pm_config"]).get("pm_config")
        backup["devices"][d["id"]] = {"name": d["name"], "pm_config": cur}
        cfg, notes = new_config(tb, d, d["kind"], cur)
        log.info("%-28s %-4s %s", d["name"], d["kind"], "; ".join(notes))
        if args.apply:
            tb.save(d["id"], {"pm_config": cfg})
    chain = next(c for c in tb.req("GET", "/api/ruleChains", params={"pageSize": 100, "page": 0})["data"] if c["name"] == CHAIN_NAME)
    backup["rule_chain"] = tb.req("GET", f"/api/ruleChain/{chain['id']['id']}/metadata")
    if args.apply:
        os.makedirs(args.backup_dir, exist_ok=True)
        path = os.path.join(args.backup_dir, f"pm_config_backup_{backup['ts']}.json")
        json.dump(backup, open(path, "w"), indent=1)
        log.info("backup written: %s", path)
    log.info("rule chain: %s", migrate_chain(tb, chain["id"]["id"], LLM_OUT_JS, args.apply) or "already up to date")
    if args.apply:
        try:
            sid = tb.req("GET", "/api/tenant/assets", params={"assetName": SETTINGS_NAME})["id"]["id"]
        except RuntimeError as exc:
            if " 404 " not in str(exc):
                raise
            sid = tb.req("POST", "/api/asset", json={"name": SETTINGS_NAME, "type": SETTINGS_TYPE,
                                                     "label": "Maintenance and predictive-maintenance configuration"})["id"]["id"]
        tb.save(sid, {"pm_templates": SEED}, etype="ASSET")
        log.info("template stored on %s (pm_templates)", SETTINGS_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
