import json

def generate_dashboard():
    def create_widget(w_id, row, col, name, label, color, title, unit=""):
        return {
          "typeFullFqn": "cards.value_card",
          "type": "latest",
          "sizeX": 8,
          "sizeY": 4,
          "row": row,
          "col": col,
          "id": w_id,
          "config": {
            "title": title,
            "showTitle": True,
            "showTitleIcon": False,
            "datasources": [
              {
                "type": "entity",
                "name": "",
                "entityAliasId": "ro-device-alias-uuid",
                "dataKeys": [
                  {
                    "name": name,
                    "type": "telemetry",
                    "label": label,
                    "color": color,
                    "units": unit,
                    "decimals": 1,
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
            "settings": {}
          }
        }

    dashboard = {
      "title": "RO Live Data Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for live RO Device Data (Value Cards)",
        "widgets": {
          "w1": create_widget("w1", 0, 0, "tds", "TDS", "#2196f3", "TDS Level", "ppm"),
          "w2": create_widget("w2", 0, 8, "temperature", "Temperature", "#f44336", "Temperature", "°C"),
          "w3": create_widget("w3", 0, 16, "conductivity", "Conductivity", "#4caf50", "Conductivity", "uS/cm"),
          "w4": create_widget("w4", 4, 0, "ph", "pH Level", "#9c27b0", "pH Level", "pH"),
          "w5": create_widget("w5", 4, 8, "salinity", "Salinity", "#ff9800", "Salinity", "ppm"),
          "w6": create_widget("w6", 4, 16, "chlorophyll", "Chlorophyll", "#009688", "Chlorophyll", "ug/L")
        },
        "states": {
          "default": {
            "name": "Live RO Overview",
            "root": True,
            "layouts": {
              "main": {
                "widgets": {
                  "w1": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 0},
                  "w2": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 8},
                  "w3": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 16},
                  "w4": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 0},
                  "w5": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 8},
                  "w6": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 16}
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
