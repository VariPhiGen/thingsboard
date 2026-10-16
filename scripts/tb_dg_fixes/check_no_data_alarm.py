"""Live check of the 'DG No Data' alarm with a '[TEST]' device (inactivity timeout 60 s).

The device sends one reading, goes silent until ThingsBoard raises 'DG No Data', then sends again,
which must clear it. The test device is deleted at the end. Its alarms reach only the notifier log.
"""
import sys
import time

import requests

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

c = ThingsBoardClient.connect(load_settings())


def call(method, path, **kw):
    res = c.session.request(method, f"{c.base_url}{path}", headers=c._headers, timeout=60, **kw)
    res.raise_for_status()
    return res.json() if res.text else None


def no_data_alarm(dev_id):
    alarms = call("GET", f"/api/alarm/DEVICE/{dev_id}", params={"pageSize": 10, "page": 0})["data"]
    return next((a for a in alarms if a["type"] == "DG No Data"), None)


dev = call("POST", "/api/device", json={"name": "[TEST] No Data check", "type": "[TEST] no-data"})
dev_id = dev["id"]["id"]
ok = False
try:
    call("POST", f"/api/plugins/telemetry/DEVICE/{dev_id}/attributes/SERVER_SCOPE", json={"inactivityTimeout": 60000})
    token = call("GET", f"/api/device/{dev_id}/credentials")["credentialsId"]
    send = lambda: requests.post(f"{c.base_url}/api/v1/{token}/telemetry", json={"power_kw": 0}, timeout=10).raise_for_status()  # noqa: E731
    send()
    start = time.time()
    while time.time() - start < 240 and not (alarm := no_data_alarm(dev_id)):
        time.sleep(10)
    if not alarm:
        sys.exit("FAIL: no 'DG No Data' alarm within 4 minutes of silence")
    print(f"raised after {time.time() - start:.0f} s of silence: {alarm['status']} | {alarm['details'].get('description')}")
    send()
    start = time.time()
    while time.time() - start < 60 and not no_data_alarm(dev_id)["status"].startswith("CLEARED"):
        time.sleep(5)
    status = no_data_alarm(dev_id)["status"]
    print(f"after new data: {status}")
    ok = status.startswith("CLEARED")
finally:
    call("DELETE", f"/api/device/{dev_id}")
    # ThingsBoard created the '[TEST] no-data' profile for the device type: remove it as well
    profile_id = dev.get("deviceProfileId", {}).get("id")
    if profile_id and call("GET", f"/api/deviceProfile/{profile_id}")["name"] == "[TEST] no-data":
        call("DELETE", f"/api/deviceProfile/{profile_id}")
    print("deleted test device and profile")
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
