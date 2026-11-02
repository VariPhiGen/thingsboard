"""Replace the plain 'High/Low Pressure' value cards on the Fire Suppression
dashboards with SVG half-gauges (red LOW zone / green HIGH zone + needle).

Each widget is a Markdown/HTML card whose text function renders the gauge
from the existing widget's telemetry key (true/1 = High, false/0 = Low).

Usage: python3 upgrade_fire_dashboard_gauges.py [dashboard_id ...]
"""
import json
import os
import re
import sys

import requests

DASHBOARD_IDS = {
    'Fire Suppression': '9da0b780-b9b9-11f1-ab9c-c1f9998e0221',
    'Fire Suppression UPS Room 2': '51158130-ca34-11f1-a8a7-c1f9998e0221',
}
COLS_PER_ROW = 3
WIDGET_W = 24 // COLS_PER_ROW
WIDGET_H = 5

GAUGE_FUNC = r"""
var label = '__LABEL__';
var row = (data && data.length) ? data[0] : null;
var raw = row ? row[label] : undefined;
var ts = row ? row[label + '|ts'] : undefined;
var hasVal = raw !== undefined && raw !== null && raw !== '';
var isHigh = raw === true || String(raw).toLowerCase() === 'true' || Number(raw) > 0;
var angle = !hasVal ? 0 : (isHigh ? 50 : -50);
var color = !hasVal ? '#9e9e9e' : (isHigh ? '#2e7d32' : '#d32f2f');
var bg = !hasVal ? '#f5f5f5' : (isHigh ? '#e8f5e9' : '#ffebee');
var status = !hasVal ? 'NO DATA' : (isHigh ? 'HIGH PRESSURE' : 'LOW PRESSURE');
var lowOp = (!hasVal || !isHigh) ? 1 : 0.25;
var highOp = (!hasVal || isHigh) ? 1 : 0.25;
var updated = '';
if (ts) {
  var d = new Date(Number(ts));
  if (!isNaN(d.getTime())) updated = 'Updated ' + d.toLocaleString();
}
var ticks = '';
for (var a = -90; a <= 90; a += 15) {
  var r1 = a % 45 === 0 ? 58 : 63;
  var rad = (a - 90) * Math.PI / 180;
  ticks += '<line x1="' + (100 + r1 * Math.cos(rad)).toFixed(1) + '" y1="' + (100 + r1 * Math.sin(rad)).toFixed(1) +
    '" x2="' + (100 + 68 * Math.cos(rad)).toFixed(1) + '" y2="' + (100 + 68 * Math.sin(rad)).toFixed(1) +
    '" stroke="#90a4ae" stroke-width="1.5"></line>';
}
var svg = '<svg viewBox="0 0 200 128" style="width:100%;height:100%;max-height:100%;display:block;">' +
  '<path d="M 18 100 A 82 82 0 0 1 100 18" fill="none" stroke="#d32f2f" stroke-width="16" stroke-linecap="round" opacity="' + lowOp + '"></path>' +
  '<path d="M 100 18 A 82 82 0 0 1 182 100" fill="none" stroke="#2e7d32" stroke-width="16" stroke-linecap="round" opacity="' + highOp + '"></path>' +
  ticks +
  '<text x="30" y="122" text-anchor="middle" font-size="12" font-weight="700" fill="#d32f2f">LOW</text>' +
  '<text x="170" y="122" text-anchor="middle" font-size="12" font-weight="700" fill="#2e7d32">HIGH</text>' +
  '<g style="transform: rotate(' + angle + 'deg); transform-origin: 100px 100px; transition: transform 0.8s cubic-bezier(.4,1.6,.6,1);">' +
  '<polygon points="96,100 100,30 104,100" fill="#37474f"></polygon></g>' +
  '<circle cx="100" cy="100" r="9" fill="#37474f"></circle>' +
  '<circle cx="100" cy="100" r="4" fill="#ffffff"></circle>' +
  '</svg>';
return '<div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:space-between;padding:12px 12px 10px;box-sizing:border-box;font-family:Roboto,sans-serif;">' +
  '<div style="font-size:16px;font-weight:600;color:#263238;">' + label + '</div>' +
  '<div style="flex:1;min-height:0;width:100%;max-width:300px;display:flex;align-items:center;justify-content:center;">' + svg + '</div>' +
  '<div style="background:' + bg + ';color:' + color + ';border:1px solid ' + color + ';border-radius:16px;padding:4px 14px;font-size:14px;font-weight:700;letter-spacing:0.5px;">' + status + '</div>' +
  '<div style="font-size:11px;color:#90a4ae;margin-top:4px;">' + updated + '</div>' +
  '</div>';
"""


def load_env(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k] = v
    return env


def gauge_widget(i, alias_id, key, label):
    row = ((i - 1) // COLS_PER_ROW) * WIDGET_H
    col = ((i - 1) % COLS_PER_ROW) * WIDGET_W
    return row, col, {
        "typeFullFqn": "system.cards.markdown_card",
        "type": "latest",
        "sizeX": WIDGET_W,
        "sizeY": WIDGET_H,
        "row": row,
        "col": col,
        "id": f"w_pressure_{i}",
        "config": {
            "title": label,
            "showTitle": False,
            "showTitleIcon": False,
            "dropShadow": True,
            "enableFullscreen": True,
            "backgroundColor": "#ffffff",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "0px",
            "datasources": [{
                "type": "entity",
                "name": "",
                "entityAliasId": alias_id,
                "dataKeys": [{
                    "name": key,
                    "type": "timeseries",
                    "label": label,
                    "color": "#03a9f4",
                    "settings": {},
                }],
            }],
            "timewindow": {"realtime": {"realtimeType": 0, "interval": 1000, "timewindowMs": 60000}},
            "settings": {
                "useMarkdownTextFunction": True,
                "markdownTextFunction": GAUGE_FUNC.replace('__LABEL__', label),
                "markdownTextPattern": "",
                "applyDefaultMarkdownStyle": False,
                "markdownCss": "",
            },
        },
    }


def upgrade(base, headers, dashboard_id):
    dashboard = requests.get(f"{base}/api/dashboard/{dashboard_id}", headers=headers).json()
    slug = re.sub(r'\W+', '_', dashboard['title']).strip('_').lower()
    backup = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"dashboard_{slug}_backup.json")
    if not os.path.exists(backup):
        with open(backup, 'w') as f:
            json.dump(dashboard, f, indent=2)
        print(f"Backup saved to {backup}")

    config = dashboard['configuration']
    widgets = config['widgets']
    layout = config['states']['default']['layouts']['main']['widgets']

    panels = []
    for w_id, w in widgets.items():
        m = re.fullmatch(r'w_pressure_(\d+)', w_id)
        if m:
            ds = w['config']['datasources'][0]
            dk = ds['dataKeys'][0]
            panels.append((int(m.group(1)), ds['entityAliasId'], dk['name'], dk['label']))

    for i, alias_id, key, label in sorted(panels):
        row, col, widget = gauge_widget(i, alias_id, key, label)
        widgets[widget['id']] = widget
        layout[widget['id']] = {"sizeX": WIDGET_W, "sizeY": WIDGET_H, "row": row, "col": col}

    res = requests.post(f"{base}/api/dashboard", json=dashboard, headers=headers)
    if res.ok:
        print(f"'{dashboard['title']}' updated with {len(panels)} gauge widgets.")
    else:
        print(f"Failed to update '{dashboard['title']}': {res.status_code} {res.text}")


def main():
    env = load_env()
    base = env['TB_BASE_URL']
    token = requests.post(f"{base}/api/auth/login",
                          json={"username": env['TB_TENANT_USER'], "password": env['TB_TENANT_PASS']}).json()['token']
    headers = {"X-Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for dashboard_id in sys.argv[1:] or DASHBOARD_IDS.values():
        upgrade(base, headers, dashboard_id)


if __name__ == '__main__':
    main()
