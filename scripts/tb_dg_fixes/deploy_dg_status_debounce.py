"""Adds DG status debounce to the root rule chain. Usage: deploy.py <backup.json> [--apply]"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

HERE = Path(__file__).parent / "rule_nodes"
ROOT_CHAIN = "1d524b90-6a70-11f1-87c3-df6f31aa9de9"

c = ThingsBoardClient.connect(load_settings())
md = c._get(f"/api/ruleChain/{ROOT_CHAIN}/metadata")
Path(sys.argv[1]).write_text(json.dumps(md, indent=1))
print("backup ->", sys.argv[1], "version", md.get("version"))

nodes = md["nodes"]
idx = {n["name"]: i for i, n in enumerate(nodes)}
if "Fetch DG State" in idx:
    sys.exit("already deployed")
has_valid, compute, alarm = idx["Has Valid DG Reading"], idx["Compute DG Status"], idx["DG Offline Alarm"]

nodes[compute]["configuration"]["jsScript"] = (HERE / "compute_dg_status.js").read_text()
nodes[alarm]["configuration"]["alarmDetailsBuildJs"] = nodes[alarm]["configuration"]["alarmDetailsBuildJs"].replace(
    "is OFF. Valid readings show RPM <= 100 and power <= 5 kW.",
    "is OFF. Valid readings have shown RPM <= 100 and power <= 5 kW for at least 2 minutes.")


def pos(i, dx, dy):
    info = nodes[i].get("additionalInfo") or {}
    return {"description": "", "layoutX": info.get("layoutX", 0) + dx, "layoutY": info.get("layoutY", 0) + dy}


fetch = len(nodes)
nodes.append({
    "type": "org.thingsboard.rule.engine.metadata.TbGetAttributesNode", "name": "Fetch DG State",
    "debugSettings": None, "singletonMode": False, "configurationVersion": 1,
    "additionalInfo": pos(has_valid, 0, 120),
    "configuration": {"fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [],
                      "serverAttributeNames": ["dg_state_confirmed", "dg_state_candidate", "dg_state_candidate_ts"],
                      "latestTsKeyNames": ["dg_status"], "tellFailureIfAbsent": False, "getLatestValueWithTs": False},
})
to_attrs = len(nodes)
nodes.append({
    "type": "org.thingsboard.rule.engine.transform.TbTransformMsgNode", "name": "DG State Attributes",
    "debugSettings": None, "singletonMode": False, "configurationVersion": 0,
    "additionalInfo": pos(compute, 0, 120),
    "configuration": {"scriptLang": "JS", "jsScript": (HERE / "dg_state_attributes.js").read_text(),
                      "tbelScript": "return {msg: msg, metadata: metadata, msgType: msgType};"},
})
save = len(nodes)
nodes.append({
    "type": "org.thingsboard.rule.engine.telemetry.TbMsgAttributesNode", "name": "Save DG State",
    "debugSettings": None, "singletonMode": False, "configurationVersion": 3,
    "additionalInfo": pos(compute, 0, 240),
    "configuration": {"processingSettings": {"type": "ON_EVERY_MESSAGE"}, "scope": "SERVER_SCOPE", "notifyDevice": False,
                      "sendAttributesUpdatedNotification": False, "updateAttributesOnlyOnValueChange": True},
})
# Copy configurationVersion of the existing node classes so TB does not try to upgrade them
for n in nodes[:fetch]:
    for new in nodes[fetch:]:
        if n["type"] == new["type"] and "configurationVersion" in n:
            new["configurationVersion"] = n["configurationVersion"]

conns = [x for x in md["connections"] if not (x["fromIndex"] == has_valid and x["toIndex"] == compute)]
conns += [
    {"fromIndex": has_valid, "toIndex": fetch, "type": "True"},
    {"fromIndex": fetch, "toIndex": compute, "type": "Success"},
    {"fromIndex": compute, "toIndex": to_attrs, "type": "Success"},
    {"fromIndex": to_attrs, "toIndex": save, "type": "Success"},
]
new_md = copy.deepcopy(md)
new_md["nodes"], new_md["connections"] = nodes, conns
for k in ("ruleChainConnections",):
    new_md.setdefault(k, md.get(k))

print("new nodes:", [n["name"] for n in nodes[fetch:]])
for x in conns:
    if fetch <= x["fromIndex"] or fetch <= x["toIndex"] or x["toIndex"] == compute:
        print(f"  {nodes[x['fromIndex']]['name']} --{x['type']}--> {nodes[x['toIndex']]['name']}")
if "--apply" in sys.argv:
    res = c.session.post(f"{c.base_url}/api/ruleChain/metadata", json=new_md, headers=c._headers, timeout=60)
    print("POST", res.status_code, res.text[:300])
    res.raise_for_status()
