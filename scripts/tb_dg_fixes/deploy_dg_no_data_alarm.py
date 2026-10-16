"""Root rule chain: a 'DG No Data' alarm when a DG device stops sending data. Usage: <backup.json> [--apply]

ThingsBoard sends an 'Inactivity Event' when a device has sent nothing for its inactivity timeout (server
default 10 min, or the device's server attribute inactivityTimeout in ms), and an 'Activity Event' when data
returns. Only DG devices (profile woodward_kg1500) raise the alarm; add profiles to the filter to cover
more devices. Devices named '[TEST] ...' are included so the path can be tested; the Telegram notifier
never sends their alarms to the real chats. Created and cleared alarms go to the Telegram webhook.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

ROOT_CHAIN = "1d524b90-6a70-11f1-87c3-df6f31aa9de9"
FILTER_JS = """// Devices whose silence raises 'DG No Data' (profile names); '[TEST] ' devices only reach the notifier log
var t = metadata.deviceType || '';
return t === 'woodward_kg1500' || t.indexOf('[TEST] ') === 0;"""
DETAILS_JS = """var dg = metadata.deviceName || 'DG Set';
var last = Number(msg.lastActivityTime);
var since = last > 0 ? new Date(last + 19800000).toISOString().substring(0, 16).replace('T', ' ') + ' IST' : 'unknown';
return {
  description: dg + ' has sent no data since ' + since + '.',
  message: dg + ' has sent no data since ' + since + ' (gateway, Modbus link or power). Its status and alarms are not being monitored.',
  recommended_action: 'Check the DG gateway power and network, and the Modbus cable to the controller.'
};"""
CLEAR_JS = """var dg = metadata.deviceName || 'DG Set';
return {description: dg + ' is sending data again.', message: dg + ' is sending data again; monitoring resumed.'};"""

c = ThingsBoardClient.connect(load_settings())
md = c._get(f"/api/ruleChain/{ROOT_CHAIN}/metadata")
Path(sys.argv[1]).write_text(json.dumps(md, indent=1))
print("backup ->", sys.argv[1], "version", md.get("version"))
nodes = md["nodes"]
idx = {n["name"]: i for i, n in enumerate(nodes)}
if "DG No Data Alarm" in idx:
    sys.exit("already deployed")
switch, telegram = idx["Message Type Switch"], idx["Telegram Webhook REST API"]
version = {n["type"]: n.get("configurationVersion", 0) for n in nodes}
info = nodes[switch].get("additionalInfo") or {}
x, y = info.get("layoutX", 0), info.get("layoutY", 0)


def add(node_type, name, configuration, dx, dy):
    nodes.append({"type": node_type, "name": name, "debugSettings": None, "singletonMode": False,
                  "configurationVersion": version.get(node_type, 0),
                  "additionalInfo": {"description": "", "layoutX": x + dx, "layoutY": y + dy},
                  "configuration": configuration})
    return len(nodes) - 1


js_filter = "org.thingsboard.rule.engine.filter.TbJsFilterNode"
inactive_filter = add(js_filter, "Is DG Device (no data)", {"scriptLang": "JS", "jsScript": FILTER_JS, "tbelScript": "return false;"}, -300, 500)
active_filter = add(js_filter, "Is DG Device (data back)", {"scriptLang": "JS", "jsScript": FILTER_JS, "tbelScript": "return false;"}, -300, 600)
create = add("org.thingsboard.rule.engine.action.TbCreateAlarmNode", "DG No Data Alarm", {
    "scriptLang": "JS", "alarmDetailsBuildJs": DETAILS_JS, "alarmDetailsBuildTbel": "return {};", "alarmType": "DG No Data",
    "severity": "MAJOR", "propagate": False, "propagateToOwner": False, "propagateToTenant": False,
    "useMessageAlarmData": False, "overwriteAlarmDetails": True, "dynamicSeverity": False, "relationTypes": []}, -50, 500)
clear = add("org.thingsboard.rule.engine.action.TbClearAlarmNode", "Clear DG No Data Alarm", {
    "scriptLang": "JS", "alarmDetailsBuildJs": CLEAR_JS, "alarmDetailsBuildTbel": "return {};", "alarmType": "DG No Data"}, -50, 600)
md["connections"] += [
    {"fromIndex": switch, "toIndex": inactive_filter, "type": "Inactivity Event"},
    {"fromIndex": switch, "toIndex": active_filter, "type": "Activity Event"},
    {"fromIndex": inactive_filter, "toIndex": create, "type": "True"},
    {"fromIndex": active_filter, "toIndex": clear, "type": "True"},
    {"fromIndex": create, "toIndex": telegram, "type": "Created"},
    {"fromIndex": clear, "toIndex": telegram, "type": "Cleared"},
]
for conn in md["connections"][-6:]:
    print(f"  {nodes[conn['fromIndex']]['name']} --{conn['type']}--> {nodes[conn['toIndex']]['name']}")
if "--apply" in sys.argv:
    res = c.session.post(f"{c.base_url}/api/ruleChain/metadata", json=md, headers=c._headers, timeout=60)
    print("POST", res.status_code, res.text[:120])
    res.raise_for_status()
