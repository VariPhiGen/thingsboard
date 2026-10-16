"""Adds energy-meter scaling ahead of the Device Profile Node. Usage: deploy_chain.py <backup.json> [--apply]"""
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
if "Scale DG Energy Meter" in idx:
    sys.exit("already deployed")
switch, profile = idx["Message Type Switch"], idx["Device Profile Node"]
cfg_version = {n["type"]: n.get("configurationVersion", 0) for n in nodes}
info = nodes[switch].get("additionalInfo") or {}
x, y = info.get("layoutX", 0), info.get("layoutY", 0)


def add(node_type, name, configuration, dx, dy):
    nodes.append({
        "type": node_type, "name": name, "debugSettings": None, "singletonMode": False,
        "configurationVersion": cfg_version.get(node_type, 0),
        "additionalInfo": {"description": "", "layoutX": x + dx, "layoutY": y + dy},
        "configuration": configuration,
    })
    return len(nodes) - 1


has = add("org.thingsboard.rule.engine.filter.TbJsFilterNode", "Has Energy Meter",
          {"scriptLang": "JS", "jsScript": (HERE / "has_energy.js").read_text(), "tbelScript": "return false;"}, 0, 200)
fetch = add("org.thingsboard.rule.engine.metadata.TbGetAttributesNode", "Fetch Energy Scale",
            {"fetchTo": "METADATA", "clientAttributeNames": [], "sharedAttributeNames": [],
             "serverAttributeNames": ["energy_kwh_scale"], "latestTsKeyNames": [],
             "tellFailureIfAbsent": False, "getLatestValueWithTs": False}, 0, 300)
scale = add("org.thingsboard.rule.engine.transform.TbTransformMsgNode", "Scale DG Energy Meter",
            {"scriptLang": "JS", "jsScript": (HERE / "scale_energy.js").read_text(),
             "tbelScript": "return {msg: msg, metadata: metadata, msgType: msgType};"}, 0, 400)

conns = [x_ for x_ in md["connections"]
         if not (x_["fromIndex"] == switch and x_["toIndex"] == profile and x_["type"] == "Post telemetry")]
conns += [
    {"fromIndex": switch, "toIndex": has, "type": "Post telemetry"},
    {"fromIndex": has, "toIndex": fetch, "type": "True"},
    {"fromIndex": has, "toIndex": profile, "type": "False"},
    {"fromIndex": fetch, "toIndex": scale, "type": "Success"},
    {"fromIndex": scale, "toIndex": profile, "type": "Success"},
    # Any failure still delivers the (unscaled) telemetry, so no data is ever dropped here
    {"fromIndex": has, "toIndex": profile, "type": "Failure"},
    {"fromIndex": fetch, "toIndex": profile, "type": "Failure"},
    {"fromIndex": scale, "toIndex": profile, "type": "Failure"},
]
md["nodes"], md["connections"] = nodes, conns
for x_ in conns:
    if x_["fromIndex"] in (switch, has, fetch, scale) and x_["type"] != "Post attributes" or x_["toIndex"] == profile:
        print(f"  {nodes[x_['fromIndex']]['name']} --{x_['type']}--> {nodes[x_['toIndex']]['name']}")
if "--apply" in sys.argv:
    res = c.session.post(f"{c.base_url}/api/ruleChain/metadata", json=md, headers=c._headers, timeout=60)
    print("POST", res.status_code, res.text[:200])
    res.raise_for_status()
