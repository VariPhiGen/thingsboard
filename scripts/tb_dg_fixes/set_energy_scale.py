"""Sets server attribute energy_kwh_scale on every woodward_kg1500 DG. Usage: set_scale.py <value>"""
import sys

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

value = float(sys.argv[1])
c = ThingsBoardClient.connect(load_settings())
for d in c.devices():
    if d.get("type") == "woodward_kg1500":
        res = c.session.post(f"{c.base_url}/api/plugins/telemetry/DEVICE/{d['id']['id']}/SERVER_SCOPE",
                             json={"energy_kwh_scale": value}, headers=c._headers, timeout=30)
        res.raise_for_status()
        print(d["name"], "energy_kwh_scale =", value)
