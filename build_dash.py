import json
import copy

def generate_dashboard():
    with open('/tmp/ts_widget.json', 'r') as f:
        ts_template = json.load(f)

    def create_card_widget(w_id, row, col, name, label, color, title, unit="", decimals=1):
        return {
          "typeFullFqn": "system.cards.value_card",
          "type": "latest",
          "sizeX": 4,
          "sizeY": 4,
          "row": row,
          "col": col,
          "id": w_id,
          "config": {
            "title": title,
            "showTitle": False,
            "showTitleIcon": False,
            "datasources": [
              {
                "type": "entity",
                "name": "",
                "entityAliasId": "12ae98c7-1ea2-52cf-64d5-763e9d993547",
                "dataKeys": [
                  {
                    "name": name,
                    "type": "timeseries",
                    "label": label,
                    "color": color,
                    "units": unit,
                    "decimals": decimals,
                    "settings": {}
                  }
                ]
              }
            ],
            "timewindow": {
              "realtime": {
                "realtimeType": 0,
                "interval": 1000,
                "timewindowMs": 60000
              }
            },
            "settings": {
              "autoScale": False,
              "valueFont": {
                "size": 36,
                "sizeUnit": "px",
                "family": "Roboto",
                "weight": "600",
                "style": "normal"
              }
            }
          }
        }

    def create_chart_widget(w_id, row, col, name, label, color, title, unit=""):
        import copy
        w = copy.deepcopy(ts_template)
        w["id"] = w_id
        w["col"] = col
        w["row"] = row
        w["sizeX"] = 8
        w["sizeY"] = 6
        w["config"]["title"] = title
        w["config"]["showTitleIcon"] = False
        
        # update dataKeys
        dk = w["config"]["datasources"][0]["dataKeys"][0]
        dk["name"] = name
        dk["type"] = "timeseries"
        dk["label"] = label
        dk["color"] = color
        dk["units"] = unit
        
        # set y-axis units based on metric
        w["config"]["settings"]["yAxes"]["default"]["units"] = unit
        
        # update alias
        w["config"]["datasources"][0]["entityAliasId"] = "12ae98c7-1ea2-52cf-64d5-763e9d993547"
        
        # Remove threshold config if exists (to avoid errors)
        if "latestDataKeys" in w["config"]["datasources"][0]:
            del w["config"]["datasources"][0]["latestDataKeys"]
        w["config"]["settings"]["thresholds"] = []
        
        return w

    metrics = [
        {"name": "chlorophyll", "label": "Chlorophyll", "color": "#009688", "unit": "ug/L", "title": "Chlorophyll"},
        {"name": "conductivity", "label": "Conductivity", "color": "#4caf50", "unit": "uS/cm", "title": "Conductivity"},
        {"name": "ec", "label": "EC", "color": "#8bc34a", "unit": "mS/cm", "title": "EC"},
        {"name": "flow_lpm", "label": "Flow LPM", "color": "#2196f3", "unit": "L/min", "title": "Flow Rate (LPM)"},
        {"name": "flow_simulated", "label": "Flow Simulated", "color": "#ff9800", "unit": "", "title": "Flow Simulated", "decimals": 0},
        {"name": "flow_total_l", "label": "Flow Total", "color": "#9c27b0", "unit": "L", "title": "Total Flow (L)"},
        {"name": "ph", "label": "pH Level", "color": "#f44336", "unit": "pH", "title": "pH Level"},
        {"name": "salinity", "label": "Salinity", "color": "#673ab7", "unit": "ppm", "title": "Salinity"},
        {"name": "tds", "label": "TDS", "color": "#3f51b5", "unit": "ppm", "title": "TDS"}
    ]

    widgets = {}
    main_widgets_layout = {}
    
    # 9 Cards (Row 0 for first 6, Row 4 for next 3)
    for i, m in enumerate(metrics):
        w_id = f"card_{i}"
        decimals = m.get("decimals", 1)
        row = 0 if i < 6 else 4
        col = (i % 6) * 4
        w = create_card_widget(w_id, row, col, m["name"], m["label"], m["color"], m["title"], m["unit"], decimals)
        widgets[w_id] = w
        main_widgets_layout[w_id] = {"sizeX": 4, "sizeY": 4, "row": row, "col": col}

    # 9 Charts (Row 8, 14, 20)
    for i, m in enumerate(metrics):
        w_id = f"chart_{i}"
        row = 8 + (i // 3) * 6
        col = (i % 3) * 8
        w = create_chart_widget(w_id, row, col, m["name"], m["label"], m["color"], m["title"], m["unit"])
        widgets[w_id] = w
        main_widgets_layout[w_id] = {"sizeX": 8, "sizeY": 6, "row": row, "col": col}

    dashboard = {
      "title": "RO Live Data Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for live RO Device Data (Cards and Charts)",
        "widgets": widgets,
        "states": {
          "default": {
            "name": "Live RO Overview",
            "root": True,
            "layouts": {
              "main": {
                "widgets": main_widgets_layout,
                "gridSettings": {
                  "backgroundColor": "#eeeeee",
                  "columns": 24,
                  "margin": 10,
                  "backgroundSizeMode": "100%"
                }
              }
            }
          }
        },
        "entityAliases": {
          "12ae98c7-1ea2-52cf-64d5-763e9d993547": {
            "id": "12ae98c7-1ea2-52cf-64d5-763e9d993547",
            "alias": "My RO Machine",
            "filter": {
              "type": "singleEntity",
              "resolveMultiple": False,
              "singleEntity": {
                "entityType": "DEVICE",
                "id": "REPLACE_ME_IN_UI"
              }
            }
          }
        },
        "filters": {},
        "timewindow": {
          "displayValue": "",
          "selectedTab": 0,
          "realtime": {
            "realtimeType": 0,
            "interval": 1000,
            "timewindowMs": 60000,
            "quickInterval": "CURRENT_DAY"
          }
        },
        "settings": {
          "stateControllerId": "entity",
          "showTitle": True,
          "showDashboardsSelect": True,
          "showEntitiesSelect": True,
          "showDashboardTimewindow": True,
          "showDashboardExport": True,
          "toolbarAlwaysOpen": True
        }
      },
      "name": "RO Live Data Dashboard"
    }
    
    with open('/home/ubuntu/thingsboard/remote_ro_dashboard.json', 'w') as f:
        json.dump(dashboard, f, indent=2)
    print("Dashboard JSON generated at /home/ubuntu/thingsboard/remote_ro_dashboard.json")

if __name__ == "__main__":
    generate_dashboard()
