"""Adds the "Run hours history" widgets (day-wise bar chart + table) to every DG dashboard.

Data: the clean per-day telemetry written by dg_run_hours_daily.py (run_hours_daily, run_hours_eod). The widgets
use no aggregation, so the 'error' text samples of run_hours cannot reach them.

DG dashboards are the ones whose entity alias is a device of the DG device profiles (infra_reports settings).
Existing widgets and the customers a dashboard is assigned to are kept; re-running replaces the two widgets.

  dashboard_run_hours_history.py --dry-run
  dashboard_run_hours_history.py --apply <backupdir>     back up each live dashboard, then save it with the widgets
"""
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.collect import classify  # noqa: E402
from infra_reports.config import load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

CHART_TITLE, TABLE_TITLE = "Run hours history (per day)", "Run hours history (table)"
TEMPLATE_TITLE = "Energy & Runtime"           # the dashboard's own chart: the new chart copies its look
HISTORY_MS = 90 * 24 * 3600 * 1000
ROW_H = 8
TABLE_CSS_MARK = "/* run-hours-history table */"
TABLE_CSS = TABLE_CSS_MARK + """
tb-timeseries-table-widget .mat-mdc-header-row,
tb-timeseries-table-widget .mat-mdc-header-cell,
tb-timeseries-table-widget th.mat-mdc-header-cell { background: #ffffff !important; z-index: 10; }"""

c = ThingsBoardClient.connect(load_settings())
settings = load_settings()


def call(method, path, **kw):
    res = c.session.request(method, f"{c.base_url}{path}", headers=c._headers, timeout=60, **kw)
    if not res.ok:
        sys.exit(f"{method} {path}: {res.status_code} {res.text[:300]}")
    return res.json() if res.text else None


def timewindow():
    return {"selectedTab": 1, "history": {"historyType": 0, "timewindowMs": HISTORY_MS, "interval": 86400000,
                                          "fixedTimewindow": {"startTimeMs": 0, "endTimeMs": 0}, "quickInterval": "CURRENT_DAY"},
            "aggregation": {"type": "NONE", "limit": 50000}, "timezone": "Asia/Kolkata"}


def key(name, label, color, decimals, units, extra=None):
    return {"name": name, "type": "timeseries", "label": label, "color": color, "settings": extra or {}, "decimals": decimals,
            "units": units, "aggregationType": None, "usePostProcessing": False, "postFuncBody": None}


def datasource(alias_id, keys):
    return {"type": "entity", "name": "", "entityAliasId": alias_id, "filterId": None, "dataKeys": keys,
            "alarmFilterConfig": {"statusList": ["ACTIVE"]}}


def widgets_for(cfg, alias_id):
    template = next(w for w in cfg["widgets"].values() if w["config"].get("title") == TEMPLATE_TITLE)
    chart_cfg = copy.deepcopy(template["config"])
    chart_cfg.update(title=CHART_TITLE, useDashboardTimewindow=False, displayTimewindow=True, timewindow=timewindow(),
                     datasources=[datasource(alias_id, [key("run_hours_daily", "Run hours", "#0891B2", 2, "h",
                                                            {"type": "bar"})])])
    chart_cfg["settings"] = dict(chart_cfg["settings"], stack=False, showLegend=False)
    chart_cfg["settings"]["yAxis"] = dict(chart_cfg["settings"]["yAxis"], label="Hours run per day")
    chart = {"type": "timeseries", "sizeX": 12, "sizeY": ROW_H, "typeFullFqn": "system.time_series_chart", "config": chart_cfg}
    table_cfg = {
        "title": TABLE_TITLE, "showTitle": True, "backgroundColor": "#FFFFFF", "color": "rgba(0, 0, 0, 0.87)",
        "padding": "0px", "useDashboardTimewindow": False, "displayTimewindow": True, "timewindow": timewindow(),
        "dropShadow": True, "enableFullscreen": True, "showLegend": False,
        "settings": {"showTimestamp": True, "showMilliseconds": False, "displayPagination": True, "defaultPageSize": 10,
                     "hideEmptyLines": True, "defaultSortOrder": "-0", "dateFormat": {"format": "yyyy-MM-dd", "lastUpdateAgo": False, "custom": False}},
        "datasources": [datasource(alias_id, [key("run_hours_daily", "Run hours (day)", "#0891B2", 2, "h"),
                                              key("run_hours_eod", "Hour meter at day end", "#475569", 1, "h")])],
        "actions": {},
    }
    table = {"type": "timeseries", "sizeX": 12, "sizeY": ROW_H, "typeFullFqn": "system.cards.timeseries_table", "config": table_cfg}
    return chart, table


def with_widgets(dash):
    cfg = dash["configuration"]
    main = cfg["states"]["default"]["layouts"]["main"]["widgets"]
    old = [i for i, w in cfg["widgets"].items() if w["config"].get("title") in (CHART_TITLE, TABLE_TITLE)]
    gap = min((main[i]["row"] for i in old if i in main), default=None)
    for wid in old:
        cfg["widgets"].pop(wid)
        main.pop(wid, None)
    if gap is not None:                             # close the gap the old widgets leave
        for l in main.values():
            if l["row"] >= gap:
                l["row"] -= ROW_H
    css = cfg["settings"].get("dashboardCss") or ""
    if TABLE_CSS_MARK not in css:                  # the sticky header of the table is transparent: rows show through it
        cfg["settings"]["dashboardCss"] = (css + "\n" + TABLE_CSS).strip()
    alias_id = next(iter(cfg["entityAliases"]))
    # directly under the dashboard's graphs; everything below moves down
    row = max(main[i]["row"] + main[i]["sizeY"] for i, w in cfg["widgets"].items() if w["typeFullFqn"] == "system.time_series_chart")
    for l in main.values():
        if l["row"] >= row:
            l["row"] += ROW_H
    for col, widget in enumerate(widgets_for(cfg, alias_id)):
        wid = str(uuid.uuid4())
        widget["id"] = wid
        cfg["widgets"][wid] = widget
        main[wid] = {"sizeX": 12, "sizeY": ROW_H, "row": row, "col": 12 * col}
    return dash


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
    new = with_widgets(copy.deepcopy(live))
    n = len(new["configuration"]["widgets"]) - len(live["configuration"]["widgets"])
    if sys.argv[1] == "--dry-run":
        print(f"{live['title']}: would add {n} widgets (assigned to {[a['title'] for a in live.get('assignedCustomers') or []]})")
        continue
    backup = Path(sys.argv[2]) / f"dashboard_before_run_hours_history_{live['id']['id']}.json"
    backup.write_text(json.dumps(live, indent=1))
    saved = call("POST", "/api/dashboard", json=new)
    print(f"{saved['title']}: saved with run-hours history (+{n} widgets), backup {backup}")
