"""Hides sensor-offline codes (32767/65535) and failed reads ('error') on the three DG dashboards.

Adds a data-key post-processing function to every numeric DG key: value cards then show N/A,
charts show a gap, gauges rest at their minimum. Text keys (status, AI fields) are not touched.

  dash_fix.py --test-copy        create '[TEST] ...' copies with the fix, print their ids
  dash_fix.py --delete <id>...   delete test copies
  dash_fix.py --apply <backupdir> back up the live dashboards and save them with the fix
  dash_fix.py --token            print a tenant JWT for the screenshot check
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

DASHBOARDS = ["09c06030-81cc-11f1-a760-b3ba4cbe1b98", "12254780-b373-11f1-9522-c1f9998e0221",
              "e643c300-b406-11f1-9522-c1f9998e0221"]
NUMERIC_KEYS = {"power_kw", "energy_kwh", "run_hours", "engine_starts", "battery_voltage", "engine_rpm",
                "coolant_temp", "oil_pressure", "frequency", "voltage", "voltage_delta", "current",
                "power_factor", "fuel_level"}
POST_FUNC = """// Modbus 'not available' codes (32767/65535, also /10 scaled) and failed reads ('error') are not
// readings: show no value (N/A on cards, a gap in charts) instead of a fake number.
var n = Number(value);
if (value === null || value === undefined || value === '' || typeof value === 'boolean' || !isFinite(n) ||
    n === 32767 || n === 65535 || n === 3276.7 || n === 6553.5) {
  return null;
}
return value;"""

c = ThingsBoardClient.connect(load_settings())


def call(method, path, **kw):
    res = c.session.request(method, f"{c.base_url}{path}", headers=c._headers, timeout=60, **kw)
    if not res.ok:
        sys.exit(f"{method} {path}: {res.status_code} {res.text[:300]}")
    return res.json() if res.text else None


def fixed(dashboard):
    d = copy.deepcopy(dashboard)
    changed = 0
    for w in d["configuration"]["widgets"].values():
        for ds in w["config"].get("datasources") or []:
            for k in ds.get("dataKeys") or []:
                if k.get("name") in NUMERIC_KEYS:
                    k["usePostProcessing"] = True
                    k["postFuncBody"] = POST_FUNC
                    changed += 1
    return d, changed


mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "--token":
    print(c._headers["X-Authorization"].split(" ", 1)[1])
elif mode == "--delete":
    for dash_id in sys.argv[2:]:
        title = call("GET", f"/api/dashboard/{dash_id}")["title"]
        if not title.startswith("[TEST] "):
            sys.exit(f"refusing to delete non-test dashboard {title!r}")
        call("DELETE", f"/api/dashboard/{dash_id}")
        print("deleted", dash_id, title)
elif mode in ("--test-copy", "--apply"):
    for dash_id in DASHBOARDS:
        live = call("GET", f"/api/dashboard/{dash_id}")
        new, changed = fixed(live)
        if mode == "--test-copy":
            for k in ("id", "version", "createdTime", "assignedCustomers", "externalId"):
                new.pop(k, None)
            new["title"] = "[TEST] " + live["title"]
            saved = call("POST", "/api/dashboard", json=new)
            print("test copy", saved["id"]["id"], saved["title"], f"({changed} keys)")
        else:
            backup = Path(sys.argv[2]) / f"dashboard_before_sensor_na_{dash_id}.json"
            backup.write_text(json.dumps(live, indent=1))
            saved = call("POST", "/api/dashboard", json=new)
            print("updated", dash_id, live["title"], f"v{live.get('version')} -> v{saved.get('version')}",
                  f"({changed} keys), backup {backup}")
else:
    sys.exit(__doc__)
