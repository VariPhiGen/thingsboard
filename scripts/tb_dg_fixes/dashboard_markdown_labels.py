"""Fixes Markdown/HTML cards of the DG dashboards that always show '--' although the device has the value.

In a Markdown card text function `data[0]` is keyed by the data key LABEL, not by its name (the fuel cards already
rely on that). "Condition Summary" (key summary, label 'Condition Summary') and "Maintenance Recommendation" (keys
maintenance_recommendation / ai_status, labels 'Recommendation' / 'Monitoring') looked values up by name, found
nothing and rendered '--'; the 'Monitoring paused' notice could never show either.

For every markdown card with a text function, each data[0]['<key name>'] lookup is changed to the key's label.
Cards that already use labels are untouched. DG dashboards are found like in dashboard_run_hours_history.py.

  dashboard_markdown_labels.py --dry-run
  dashboard_markdown_labels.py --apply <backupdir>
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.collect import classify  # noqa: E402
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

settings = load_settings()
c = ThingsBoardClient.connect(settings)


def call(method, path, **kw):
    res = c.session.request(method, f"{c.base_url}{path}", headers=c._headers, timeout=60, **kw)
    if not res.ok:
        sys.exit(f"{method} {path}: {res.status_code} {res.text[:300]}")
    return res.json() if res.text else None


def fix(dash):
    """(dash, [(card title, name, label)]) with name lookups replaced by label lookups."""
    changes = []
    for w in dash["configuration"]["widgets"].values():
        cfg = w["config"]
        fn = (cfg.get("settings") or {}).get("markdownTextFunction")
        if w.get("typeFullFqn") != "system.cards.markdown_card" or not fn:
            continue
        for ds in cfg.get("datasources", []):
            for k in ds.get("dataKeys", []):
                name, label = k["name"], k.get("label") or k["name"]
                for quote in ("'", '"'):
                    old = f"data[0][{quote}{name}{quote}]"
                    if name != label and old in fn:
                        fn = fn.replace(old, f"data[0][{quote}{label}{quote}]")
                        changes.append((cfg.get("title"), name, label))
        cfg["settings"]["markdownTextFunction"] = fn
    return dash, changes


def dg_dashboards():
    devices = {d["id"]["id"]: d for d in c.devices()}
    for d in c._paged("/api/tenant/dashboards"):
        dash = call("GET", f"/api/dashboard/{d['id']['id']}")
        ids = [a["filter"].get("singleEntity", {}).get("id") for a in dash["configuration"].get("entityAliases", {}).values()]
        if len(ids) == 1 and ids[0] in devices and classify(devices[ids[0]], settings.profiles) == "dg":
            yield dash


if len(sys.argv) < 2 or sys.argv[1] not in ("--dry-run", "--apply"):
    sys.exit(__doc__)
for live in dg_dashboards():
    new, changes = fix(copy.deepcopy(live))
    print(f"{live['title']}: {len(changes)} lookups -> label: {changes}")
    if sys.argv[1] == "--apply" and changes:
        backup = Path(sys.argv[2]) / f"dashboard_before_markdown_labels_{live['id']['id']}.json"
        backup.write_text(json.dumps(live, indent=1))
        call("POST", "/api/dashboard", json=new)
        print("   saved, backup", backup)
