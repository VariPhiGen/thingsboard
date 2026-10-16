"""Divides the stored energy_kwh history of the woodward_kg1500 DGs by 10 (scale 0.1).

Dry run by default; --apply writes. Safe to re-run: a point that already has energy_kwh_raw at its
timestamp (written by the rule chain or by an earlier run) is skipped, so nothing is scaled twice.
Text values ('error') and sensor-offline codes are left as they are. The 19 Sep 2026 simulator
window of DG SET1 (source=dummy) is not touched.
Refuses to run unless the device's energy_kwh_scale attribute is 0.1, i.e. live data is already scaled.
"""
import sys
import time
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import REPORT_TZ, load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

SCALE = 0.1
DAY = 86_400_000
START = int(datetime(2026, 7, 1, tzinfo=REPORT_TZ).timestamp() * 1000)
# DG SET1 simulator run (source=dummy): 2026-09-19 15:42:13 - 17:19:43 IST
DUMMY = {"DG SET1": (int(datetime(2026, 9, 19, 15, 42, tzinfo=REPORT_TZ).timestamp() * 1000),
                     int(datetime(2026, 9, 19, 17, 20, tzinfo=REPORT_TZ).timestamp() * 1000))}
BATCH = 1000
apply = "--apply" in sys.argv

c = ThingsBoardClient.connect(load_settings())


def scaled(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v in (32767, 65535):
        return None
    if isinstance(v, int) and v % 10 == 0:
        return v // 10
    return round(v * SCALE, 3)


def post(dev_id, entries):
    url = f"{c.base_url}/api/plugins/telemetry/DEVICE/{dev_id}/timeseries/ANY"
    for attempt in range(3):
        res = c.session.post(url, json=entries, headers=c._headers, timeout=120)
        if res.ok:
            return
        time.sleep(2 * (attempt + 1))
    res.raise_for_status()


for d in c.devices():
    if d.get("type") != "woodward_kg1500":
        continue
    dev_id, name = d["id"]["id"], d["name"]
    attrs = {a["key"]: a["value"] for a in c._get(
        f"/api/plugins/telemetry/DEVICE/{dev_id}/values/attributes/SERVER_SCOPE", {"keys": "energy_kwh_scale"})}
    if apply and str(attrs.get("energy_kwh_scale")) not in ("0.1", "0.10"):
        sys.exit(f"{name}: energy_kwh_scale is {attrs.get('energy_kwh_scale')!r}, not 0.1 - enable live scaling first")
    end = int(time.time() * 1000)
    dummy = DUMMY.get(name)
    counts = {"rescaled": 0, "already_scaled": 0, "text_or_code": 0, "dummy_skipped": 0}
    samples, pending = [], []
    t = START
    while t < end:
        r = c._get(f"/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries",
                   {"keys": "energy_kwh,energy_kwh_raw", "startTs": t, "endTs": min(t + DAY, end),
                    "limit": 200000, "orderBy": "ASC", "useStrictDataTypes": "true"})
        raw_ts = {p["ts"] for p in r.get("energy_kwh_raw", [])}
        for p in r.get("energy_kwh", []):
            ts, v = p["ts"], p["value"]
            if ts in raw_ts:
                counts["already_scaled"] += 1
            elif dummy and dummy[0] <= ts < dummy[1]:
                counts["dummy_skipped"] += 1
            elif (new := scaled(v)) is None:
                counts["text_or_code"] += 1
            else:
                counts["rescaled"] += 1
                pending.append({"ts": ts, "values": {"energy_kwh": new, "energy_kwh_raw": v}})
                if len(samples) < 3 or counts["rescaled"] % 200000 == 0:
                    samples.append((datetime.fromtimestamp(ts / 1000, REPORT_TZ).strftime("%m-%d %H:%M"), v, new))
        if apply:
            for i in range(0, len(pending), BATCH):
                post(dev_id, pending[i:i + BATCH])
        pending = []
        t += DAY
    print(f"{name}: {'WROTE' if apply else 'would rescale'} {counts}  e.g. {samples}")
