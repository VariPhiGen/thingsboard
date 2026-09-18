import json

def generate_dashboard():
    with open('/tmp/ts_widget.json', 'r') as f:
        ts_template = json.load(f)

    def create_widget(w_id, col, name, label, color, title, unit=""):
        import copy
        w = copy.deepcopy(ts_template)
        w["id"] = w_id
        w["col"] = col
        w["row"] = 0
        w["sizeX"] = 8
        w["sizeY"] = 6
        w["title"] = title
        
        # update dataKeys
        dk = w["config"]["datasources"][0]["dataKeys"][0]
        dk["name"] = name
        dk["label"] = label
        dk["color"] = color
        dk["units"] = unit
        
        # update alias
        w["config"]["datasources"][0]["entityAliasId"] = "ro-device-alias-uuid"
        return w

    dashboard = {
      "title": "RO Live Data Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for live RO Device Data",
        "widgets": {
          "w1": create_widget("w1", 0, "tds", "TDS", "#2196f3", "TDS Level", "ppm"),
          "w2": create_widget("w2", 8, "temperature", "Temperature", "#f44336", "Temperature", "°C"),
          "w3": create_widget("w3", 16, "conductivity", "Conductivity", "#4caf50", "Conductivity", "uS/cm")
        },
        "states": {
          "default": {
            "name": "Live RO Overview",
            "root": True,
            "layouts": {
              "main": {
                "widgets": {
                  "w1": {"sizeX": 8, "sizeY": 6, "row": 0, "col": 0},
                  "w2": {"sizeX": 8, "sizeY": 6, "row": 0, "col": 8},
                  "w3": {"sizeX": 8, "sizeY": 6, "row": 0, "col": 16}
                },
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
          "ro-device-alias-uuid": {
            "id": "ro-device-alias-uuid",
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

if __name__ == "__main__":
    generate_dashboard()
