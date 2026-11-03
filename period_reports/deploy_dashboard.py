"""Create/update the ThingsBoard widgets and the "Reports & Maintenance" dashboard (idempotent).

  python3 -m period_reports.deploy_dashboard
"""
import json
import os
import sys

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE_ALIAS, BUNDLE_TITLE = "virtuoso_reports", "Virtuoso Reports"
DASHBOARD_TITLE = "Reports & Maintenance"
LIBRARY_ASSET, LIBRARY_TYPE = "Maintenance Document Library", "Maintenance Library"
SETTINGS_ASSET, SETTINGS_TYPE = "Maintenance Settings", "Maintenance Settings"
SETTINGS_SEED = os.path.join(os.path.dirname(HERE), "cmms", "settings_seed.json")


def read(name):
    with open(os.path.join(HERE, "widgets", name)) as f:
        return f.read()


class Api:
    def __init__(self):
        self.client = ThingsBoardClient.connect(load_settings())
        self.s, self.base, self.h = self.client.session, self.client.base_url, self.client._headers

    def get(self, path, **params):
        r = self.s.get(self.base + path, headers=self.h, params=params, timeout=60)
        return r.json() if r.status_code == 200 and r.text else None

    def post(self, path, body):
        r = self.s.post(self.base + path, headers=dict(self.h, **{"Content-Type": "application/json"}), json=body, timeout=60)
        if not r.ok:
            raise RuntimeError(f"POST {path}: {r.status_code} {r.text[:400]}")
        return r.json() if r.text else None


def widget_type(api, alias, name, wtype, css, js, size, default_config, description):
    fqn = f"{BUNDLE_ALIAS}.{alias}"
    existing = api.get("/api/widgetType", fqn=f"tenant.{fqn}")   # tenant widget types resolve with this prefix
    body = {
        "fqn": fqn, "name": name, "description": description, "deprecated": False, "scada": False,
        "descriptor": {"type": wtype, "sizeX": size[0], "sizeY": size[1], "resources": [], "templateHtml": "",
                       "templateCss": css, "controllerScript": js, "settingsSchema": "{}",
                       "dataKeySettingsSchema": "{}", "defaultConfig": json.dumps(default_config)},
    }
    if existing:
        body.update(id=existing["id"], version=existing.get("version"), tenantId=existing.get("tenantId"))
    return api.post("/api/widgetType", body)


def ensure_settings(api):
    """Asset 'Maintenance Settings' with cmms_settings; the seed file is written only when nothing is configured yet."""
    asset = api.get("/api/tenant/assets", assetName=SETTINGS_ASSET)
    if not asset:
        asset = api.post("/api/asset", {"name": SETTINGS_ASSET, "type": SETTINGS_TYPE,
                                        "label": "Maintenance and predictive-maintenance configuration"})
    sid = asset["id"]["id"]
    cur = api.get(f"/api/plugins/telemetry/ASSET/{sid}/values/attributes/SERVER_SCOPE", keys="cmms_settings") or []
    if cur:
        settings = json.loads(cur[0]["value"]) if isinstance(cur[0]["value"], str) else cur[0]["value"]
        print("maintenance settings: existing configuration kept")
    else:
        settings = {k: v for k, v in json.load(open(SETTINGS_SEED)).items() if not k.startswith("_")}
        api.post(f"/api/plugins/telemetry/ASSET/{sid}/attributes/SERVER_SCOPE",
                 {"cmms_settings": json.dumps(settings), "cmms_settings_rev": 1})
        print("maintenance settings: seeded from", SETTINGS_SEED)
    return settings


def report_api_url(api):
    """PERIOD_REPORTS_API_URL, else the URL already configured in the live Equipment Reports widget."""
    url = os.environ.get("PERIOD_REPORTS_API_URL")
    if url:
        return url
    dash = next((d for d in api.get("/api/tenant/dashboards", pageSize=200, page=0)["data"] if d["title"] == DASHBOARD_TITLE), None)
    if dash:
        full = api.get(f"/api/dashboard/{dash['id']['id']}")
        w = (full["configuration"].get("widgets") or {}).get("reports")
        if w and (w["config"].get("settings") or {}).get("apiUrl"):
            return w["config"]["settings"]["apiUrl"]
    raise SystemExit("Set PERIOD_REPORTS_API_URL (URL of the period-report download API)")


def main():
    api = Api()
    settings = ensure_settings(api)
    API_URL = report_api_url(api)
    EQUIPMENT_TYPES = settings["equipment_profiles"]
    bundles = api.get("/api/widgetsBundles", pageSize=100, page=0) or {"data": []}
    bundle = next((b for b in bundles["data"] if b.get("alias") == BUNDLE_ALIAS), None)
    if not bundle:
        bundle = api.post("/api/widgetsBundle", {"alias": BUNDLE_ALIAS, "title": BUNDLE_TITLE,
                                                 "description": "Equipment reports and maintenance log"})
    report_cfg = {"showTitle": True, "title": "Equipment Reports", "backgroundColor": "#ffffff", "padding": "0px",
                  "dropShadow": True, "settings": {"apiUrl": API_URL}, "datasources": []}
    rd = widget_type(api, "report_download", "Equipment Report Download", "static", read("report_download.css"),
                     read("report_download.js"), (10, 9), report_cfg,
                     "Daily/weekly/monthly/custom equipment reports as PDF or Excel")
    planner_cfg = {"showTitle": True, "title": "Maintenance Management", "backgroundColor": "#ffffff", "padding": "0px",
                   "dropShadow": True, "settings": {}, "datasources": []}
    mp = widget_type(api, "maintenance_planner", "Maintenance Management", "latest", read("maintenance_planner.css"),
                     read("maintenance_planner.js"), (24, 16), planner_cfg,
                     "CMMS: work orders, maintenance plans, technical documents and KPIs")
    api.post(f"/api/widgetsBundle/{bundle['id']['id']}/widgetTypeFqns", [rd["fqn"], mp["fqn"]])
    print("widget types:", rd["fqn"], mp["fqn"])

    # Asset that holds the documents that apply to all equipment (tenant attributes are read-only for tenant admins)
    lib = api.get("/api/tenant/assets", assetName=LIBRARY_ASSET)
    if not lib:
        lib = api.post("/api/asset", {"name": LIBRARY_ASSET, "type": LIBRARY_TYPE, "label": "Manuals, SOPs and checklists for all equipment"})
    print("document library asset:", lib["id"]["id"])
    live_tw = {"realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}}

    alias_id = "reports-all-equipment"
    aliases = {alias_id: {"id": alias_id, "alias": "All monitored equipment", "filter": {
        "type": "deviceType", "resolveMultiple": True, "deviceTypes": EQUIPMENT_TYPES, "deviceType": None,
        "deviceNameFilter": ""}}}
    widgets = {
        "planner": {"typeFullFqn": f"tenant.{mp['fqn']}", "type": "latest", "sizeX": 24, "sizeY": 16, "row": 0, "col": 0,
                    "id": "planner",
                    "config": dict(planner_cfg, datasources=[], timewindow=live_tw)},
        "reports": {"typeFullFqn": f"tenant.{rd['fqn']}", "type": "static", "sizeX": 12, "sizeY": 10, "row": 16,
                    "col": 0, "id": "reports", "config": report_cfg},
        "about": {"typeFullFqn": "system.cards.markdown_card", "type": "static", "sizeX": 12, "sizeY": 10, "row": 16,
                  "col": 12, "id": "about",
                  "config": {"showTitle": True, "title": "What the reports contain", "backgroundColor": "#ffffff",
                             "padding": "12px", "dropShadow": True, "datasources": [],
                             "settings": {"useMarkdownTextFunction": False, "applyDefaultMarkdownStyle": True,
                                          "markdownTextPattern": read("about.md"), "markdownCss": ""}}},
    }
    cfg = {
        "description": "Maintenance management (CMMS) and equipment period reports", "widgets": widgets,
        "states": {"default": {"name": DASHBOARD_TITLE, "root": True, "layouts": {"main": {
            "widgets": {k: {"sizeX": v["sizeX"], "sizeY": v["sizeY"], "row": v["row"], "col": v["col"]} for k, v in widgets.items()},
            "gridSettings": {"backgroundColor": "#F8FAFC", "columns": 24, "margin": 12, "outerMargin": True,
                             "backgroundSizeMode": "100%"}}}}},
        "entityAliases": aliases, "filters": {},
        "timewindow": {"selectedTab": 0, "realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}},
        "settings": {"stateControllerId": "entity", "showTitle": True, "showDashboardsSelect": True,
                     "showEntitiesSelect": False, "showDashboardTimewindow": False, "showDashboardExport": False,
                     "toolbarAlwaysOpen": True},
    }
    dashes = api.get("/api/tenant/dashboards", pageSize=200, page=0)["data"]
    existing = next((d for d in dashes if d["title"] == DASHBOARD_TITLE), None)
    body = {"title": DASHBOARD_TITLE, "configuration": cfg}
    if existing:
        full = api.get(f"/api/dashboard/{existing['id']['id']}")
        body.update(id=full["id"], version=full.get("version"))
    res = api.post("/api/dashboard", body)
    print("dashboard:", res["id"]["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
