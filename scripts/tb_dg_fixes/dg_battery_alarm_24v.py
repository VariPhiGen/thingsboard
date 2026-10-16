"""DG 'Low Battery Voltage' alarm for the 24 V starter battery. Usage: dg_battery_alarm_24v.py <backupdir> [--apply]

The old rule fired below 11.5 V (a 12 V threshold), so it could never trigger on the 24 V system
(normal 26-28 V). New rule: below 24.0 V for 3 minutes; it clears at 24.5 V. The battery dips to about
23 V for up to 80 s while the engine cranks, and that dip must not raise an alarm.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

PROFILES = ("woodward_kg1500", "woodward_kg150")
LOW_V, CLEAR_V, HOLD_S = 24.0, 24.5, 180


def value(v):
    return {"defaultValue": v, "userValue": None, "dynamicValue": None}


def fix(alarm):
    rule = alarm["createRules"]["WARNING"]
    rule["condition"]["condition"] = [{
        "key": {"type": "TIME_SERIES", "key": "battery_voltage"}, "valueType": "NUMERIC", "value": None,
        # above 5 V: a missing or zero reading is not a flat battery
        "predicate": {"type": "COMPLEX", "operation": "AND", "predicates": [
            {"type": "NUMERIC", "operation": "GREATER", "value": value(5.0)},
            {"type": "NUMERIC", "operation": "LESS", "value": value(LOW_V)}]}}]
    rule["condition"]["spec"] = {"type": "DURATION", "unit": "SECONDS", "predicate": value(HOLD_S)}
    rule["alarmDetails"] = (f"Low Battery Voltage detected: ${{battery_voltage}} V "
                            f"(below {LOW_V:g} V for {HOLD_S // 60} minutes; normal 26-28 V)")
    alarm["clearRule"]["condition"]["condition"][0]["predicate"] = {
        "type": "NUMERIC", "operation": "GREATER_OR_EQUAL", "value": value(CLEAR_V)}


c = ThingsBoardClient.connect(load_settings())
for p in c._get("/api/deviceProfiles", {"pageSize": 50, "page": 0})["data"]:
    if p["name"] not in PROFILES:
        continue
    full = c._get(f"/api/deviceProfile/{p['id']['id']}")
    backup = Path(sys.argv[1]) / f"profile_before_battery_24v_{p['name']}.json"
    backup.write_text(json.dumps(full, indent=1))
    for alarm in full["profileData"]["alarms"]:
        if alarm["alarmType"] == "Low Battery Voltage":
            fix(alarm)
    if "--apply" in sys.argv:
        res = c.session.post(f"{c.base_url}/api/deviceProfile", json=full, headers=c._headers, timeout=60)
        res.raise_for_status()
        print("updated", p["name"], "backup", backup)
    else:
        print("would update", p["name"], "backup", backup)
