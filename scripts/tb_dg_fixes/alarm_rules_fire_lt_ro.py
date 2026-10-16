"""Correct alarm rules for the Fire Suppression, LT Panels and RO Plant device profiles.

  alarm_rules_fire_lt_ro.py --test-clone           create '[TEST] <profile>' copies with the new rules
  alarm_rules_fire_lt_ro.py --apply <backupdir>    back up the live profiles and apply the new rules

Fire: the old rules read keys the panel never sends (fire_panel_N_*), so no fire alarm could fire.
They now use the keys the panel sends and the meaning the Fire report uses (true = pressure normal):
a cylinder alarm is raised when cylinder_pressure_N is false for 30 s while the input module reports
(di_raw != 0). di_raw = 0 means every input reads 0 at once, which is an input-module fault and gets
its own alarm. The fire_suppression_N_* keys of the newer panel firmware get no rules yet: what
true/false means for them must be confirmed on site.
LT: Overcurrent fired above 85 A on every panel, while transformers normally carry 600-1000 A. The
provisional limits are 110 % of the 30-day 99.9th-percentile load, held for 60 s so motor inrush does
not count. Replace them with each panel's rated current when it is known.
RO: High TDS fired at 175 ppm while the RO report calls < 200 ppm optimal. It is now WARNING above
200 ppm and CRITICAL above 500 ppm, the report's bands. Low Water Flow must last 10 minutes.
Every numeric rule ignores sensor-offline codes (>= 30000).
"""
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

FIRE, LT, RO = "LT Panel Fire Profile", "LT Panels Profile", "RO System Profile"
# Provisional overcurrent limits in A (110 % of the 30-day p99.9 load, 16 Oct 2026)
LT_PANELS = [  # (label, key prefix, overcurrent limit)
    ("EVM Charger", "EVM_Charger", 110), ("Electrical Room 1", "Electrical_room_1", 1070),
    ("UPS Room 1", "UPS_Room_1", 890), ("Transformer 1", "Transformer_1", 1150),
    ("Transformer 2", "Transformer_2", 910), ("Transformer 3", "Transformer_3", 110),
    ("UPS Panel 2", "UPS_Panel_2", 110), ("Fire Fighting Wall", "Fire_fighting_wall", 110),
]
SENSOR_CODE_MIN = 30000.0


def val(v):
    return {"defaultValue": v, "userValue": None, "dynamicValue": None}


def num(key, *preds, op="AND"):
    predicates = [{"type": "NUMERIC", "operation": o, "value": val(float(v))} for o, v in preds]
    predicate = predicates[0] if len(predicates) == 1 else {"type": "COMPLEX", "operation": op, "predicates": predicates}
    return {"key": {"type": "TIME_SERIES", "key": key}, "valueType": "NUMERIC", "value": None, "predicate": predicate}


def boolean(key, value):
    return {"key": {"type": "TIME_SERIES", "key": key}, "valueType": "BOOLEAN", "value": None,
            "predicate": {"type": "BOOLEAN", "operation": "EQUAL", "value": val(value)}}


def spec(seconds):
    return {"type": "DURATION", "unit": "SECONDS", "predicate": val(seconds)} if seconds else {"type": "SIMPLE"}


def rule(conditions, details, seconds=0):
    return {"condition": {"condition": conditions, "spec": spec(seconds)}, "schedule": None,
            "alarmDetails": details, "dashboardId": None}


def alarm(alarm_id, alarm_type, create, clear_conditions):
    return {"id": alarm_id, "alarmType": alarm_type, "createRules": create,
            "clearRule": {"condition": {"condition": clear_conditions, "spec": {"type": "SIMPLE"}}, "schedule": None,
                          "alarmDetails": None, "dashboardId": None},
            "propagate": True, "propagateToOwner": False, "propagateToTenant": True, "propagateRelationTypes": None}


def fire_alarms():
    alarms = [alarm(f"cylinder_{n}_low_pressure_alarm", f"Fire Cylinder {n} Low Pressure",
                    {"CRITICAL": rule([boolean(f"cylinder_pressure_{n}", False), num("di_raw", ("NOT_EQUAL", 0))],
                                      f"Fire suppression cylinder {n} pressure is LOW (pressure switch open for 30 s). "
                                      f"Inspect the cylinder immediately.", 30)},
                    [boolean(f"cylinder_pressure_{n}", True)])
              for n in range(1, 10)]
    alarms += [
        alarm("fire_input_fault_alarm", "Fire Panel Input Fault",
              {"CRITICAL": rule([num("di_raw", ("EQUAL", 0))],
                                "All fire panel inputs read 0 for 60 s: the input module or its wiring has failed, "
                                "so cylinder pressure is NOT being monitored.", 60)},
              [num("di_raw", ("NOT_EQUAL", 0))]),
        alarm("fire_low_pressure_line_alarm", "Fire Low Pressure Line",
              {"CRITICAL": rule([boolean("low_pressure", False)], "Fire suppression low-pressure line is LOW for 30 s.", 30)},
              [boolean("low_pressure", True)]),
        alarm("fire_high_pressure_line_alarm", "Fire High Pressure Line",
              {"CRITICAL": rule([boolean("high_pressure", False)], "Fire suppression high-pressure line alarm for 30 s.", 30)},
              [boolean("high_pressure", True)]),
        alarm("fire_relay_offline_alarm", "Fire Relay Gateway Offline",
              {"MAJOR": rule([boolean("relay_online", False)], "Fire panel relay gateway reports OFFLINE for 60 s.", 60)},
              [boolean("relay_online", True)]),
    ]
    return alarms


def lt_alarms():
    alarms = []
    for label, prefix, limit in LT_PANELS:
        v, i = f"{prefix}_voltage", f"{prefix}_current"
        alarms.append(alarm(f"{prefix}_high_voltage_alarm", f"{label} High Voltage",
                            {"CRITICAL": rule([num(v, ("GREATER", 457), ("LESS", 1000))],
                                              f"High voltage on {label}: ${{{v}}} V (limit 457 V = 415 V + 10 %)", 30)},
                            [num(v, ("LESS_OR_EQUAL", 457))]))
        alarms.append(alarm(f"{prefix}_overcurrent_alarm", f"{label} Overcurrent",
                            {"CRITICAL": rule([num(i, ("GREATER", limit), ("LESS", SENSOR_CODE_MIN))],
                                              f"Overcurrent on {label}: ${{{i}}} A (above {limit} A for 60 s)", 60)},
                            [num(i, ("LESS_OR_EQUAL", limit))]))
    return alarms


def ro_alarms():
    return [
        alarm("high_tds_alarm", "High TDS Alert",
              {"CRITICAL": rule([num("tds", ("GREATER", 500), ("LESS", SENSOR_CODE_MIN))],
                                "TDS is HIGH: ${tds} ppm (above 500 ppm). Water is not fit for use.", 60),
               "WARNING": rule([num("tds", ("GREATER", 200), ("LESS", SENSOR_CODE_MIN))],
                               "TDS above optimal: ${tds} ppm (optimal below 200 ppm)", 60)},
              [num("tds", ("LESS_OR_EQUAL", 200))]),
        alarm("low_water_flow_alarm", "Low Water Flow Warning",
              {"WARNING": rule([num("water_flow", ("GREATER_OR_EQUAL", 0), ("LESS", 1))],
                               "Permeate water flow below 1 L/min for 10 minutes: ${water_flow} L/min", 600)},
              [num("water_flow", ("GREATER_OR_EQUAL", 1))]),
        alarm("high_ro_pressure_alarm", "High RO Pressure Warning",
              {"WARNING": rule([num("pressure", ("GREATER", 65), ("LESS", SENSOR_CODE_MIN))],
                               "RO membrane pressure high: ${pressure} psi (above 65 psi)", 30)},
              [num("pressure", ("LESS_OR_EQUAL", 65))]),
    ]


NEW_ALARMS = {FIRE: fire_alarms, LT: lt_alarms, RO: ro_alarms}

c = ThingsBoardClient.connect(load_settings())


def call(method, path, **kw):
    res = c.session.request(method, f"{c.base_url}{path}", headers=c._headers, timeout=60, **kw)
    if not res.ok:
        sys.exit(f"{method} {path}: {res.status_code} {res.text[:300]}")
    return res.json() if res.text else None


profiles = {p["name"]: p for p in call("GET", "/api/deviceProfiles", params={"pageSize": 100, "page": 0})["data"]}
mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "--test-clone":
    out = {}
    for name, build in NEW_ALARMS.items():
        prof = copy.deepcopy(call("GET", f"/api/deviceProfile/{profiles[name]['id']['id']}"))
        for k in ("id", "createdTime", "version", "provisionDeviceKey", "externalId", "default"):
            prof.pop(k, None)
        prof["name"] = f"[TEST] {name}"
        prof["profileData"]["alarms"] = build()
        for a in prof["profileData"]["alarms"]:
            a["id"] = str(uuid.uuid4())  # unique ids for the copy
        out[name] = call("POST", "/api/deviceProfile", json=prof)["id"]["id"]
        print("test profile", prof["name"], out[name], len(prof["profileData"]["alarms"]), "alarms")
    print(json.dumps(out))
elif mode == "--apply":
    for name, build in NEW_ALARMS.items():
        full = call("GET", f"/api/deviceProfile/{profiles[name]['id']['id']}")
        backup = Path(sys.argv[2]) / f"profile_before_alarm_rules_v2_{name.replace(' ', '_')}.json"
        backup.write_text(json.dumps(full, indent=1))
        before = [a["alarmType"] for a in full["profileData"]["alarms"]]
        full["profileData"]["alarms"] = build()
        saved = call("POST", "/api/deviceProfile", json=full)
        print(f"updated {name}: {len(before)} -> {len(saved['profileData']['alarms'])} alarms, backup {backup}")
else:
    sys.exit(__doc__)
