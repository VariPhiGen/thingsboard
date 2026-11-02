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
API_URL = "https://n8n.variphi.com/reports-api/v1/period-reports"
EQUIPMENT_TYPES = ["woodward_kg1500", "LT Panels Profile", "RO System Profile", "LT Panel Fire Profile"]


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


def main():
    api = Api()
    bundles = api.get("/api/widgetsBundles", pageSize=100, page=0) or {"data": []}
    bundle = next((b for b in bundles["data"] if b.get("alias") == BUNDLE_ALIAS), None)
    if not bundle:
        bundle = api.post("/api/widgetsBundle", {"alias": BUNDLE_ALIAS, "title": BUNDLE_TITLE,
                                                 "description": "Equipment reports and maintenance log"})
    report_cfg = {"showTitle": True, "title": "Equipment Reports", "backgroundColor": "#ffffff", "padding": "0px",
                  "dropShadow": True, "settings": {"apiUrl": API_URL}, "datasources": []}
    maint_cfg = {"showTitle": True, "title": "Maintenance Log", "backgroundColor": "#ffffff", "padding": "0px",
                 "dropShadow": True, "settings": {}, "datasources": []}
    rd = widget_type(api, "report_download", "Equipment Report Download", "static", read("report_download.css"),
                     read("report_download.js"), (10, 9), report_cfg,
                     "Daily/weekly/monthly/custom equipment reports as PDF or Excel")
    ml = widget_type(api, "maintenance_log", "Maintenance Log", "latest", read("maintenance_log.css"),
                     read("maintenance_log.js"), (14, 18), maint_cfg,
                     "Record maintenance work; resets the DG service-due counter")
    api.post(f"/api/widgetsBundle/{bundle['id']['id']}/widgetTypeFqns", [rd["fqn"], ml["fqn"]])
    print("widget types:", rd["fqn"], ml["fqn"])

    alias_id = "reports-all-equipment"
    aliases = {alias_id: {"id": alias_id, "alias": "All monitored equipment", "filter": {
        "type": "deviceType", "resolveMultiple": True, "deviceTypes": EQUIPMENT_TYPES, "deviceType": None,
        "deviceNameFilter": ""}}}
    widgets = {
        "reports": {"typeFullFqn": f"tenant.{rd['fqn']}", "type": "static", "sizeX": 9, "sizeY": 10, "row": 0,
                    "col": 0, "id": "reports", "config": report_cfg},
        "maintenance": {"typeFullFqn": f"tenant.{ml['fqn']}", "type": "latest", "sizeX": 15, "sizeY": 20, "row": 0,
                        "col": 9, "id": "maintenance",
                        "config": dict(maint_cfg, datasources=[{"type": "entity", "name": "", "entityAliasId": alias_id,
                                                                "dataKeys": [{"name": "run_hours", "type": "timeseries",
                                                                              "label": "run_hours", "color": "#607d8b",
                                                                              "settings": {}}]}],
                                       timewindow={"realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}})},
        "about": {"typeFullFqn": "system.cards.markdown_card", "type": "static", "sizeX": 9, "sizeY": 10, "row": 10,
                  "col": 0, "id": "about",
                  "config": {"showTitle": True, "title": "What the reports contain", "backgroundColor": "#ffffff",
                             "padding": "12px", "dropShadow": True, "datasources": [],
                             "settings": {"useMarkdownTextFunction": False, "applyDefaultMarkdownStyle": True,
                                          "markdownTextPattern": read("about.md"), "markdownCss": ""}}},
    }
    cfg = {
        "description": "Equipment period reports and maintenance log", "widgets": widgets,
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
