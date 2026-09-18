import json

def generate_dashboard():
    # We will build an HTML Value Card template manually because it is simple and highly customizable
    def create_widget(w_id, row, col, name, label, color, title, unit=""):
        html_content = f"""
<div class='card'>
    <div class='content'>
        <div class='title' style='color: {color};'>{title}</div>
        <div class='value'>
            ${{{label}:1}} <span class='unit'>{unit}</span>
        </div> 
    </div>
</div>
"""
        css_content = """
.card {
   width: 100%;
   height: 100%;
   border: 1px solid #E0E0E0;
   box-sizing: border-box;
   background-color: #ffffff;
   border-radius: 8px;
   box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}

.card .content {
   padding: 20px 10px;
   display: flex;
   flex-direction: column;
   align-items: center;
   justify-content: center;
   height: 100%;
   box-sizing: border-box;
}

.card .title {
    font-size: 1.2em;
    font-weight: 600;
    margin-bottom: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.card .value {
    font-weight: 700;
    font-size: 3.5em;
    line-height: 1.1em;
    text-align: center;
    color: #333333;
}

.card .unit {
    font-size: 0.4em;
    color: #888888;
    font-weight: 500;
}
"""
        return {
          "typeFullFqn": "system.cards.html_value_card",
          "type": "latest",
          "sizeX": 8,
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
            "settings": {
                "cardHtml": html_content,
                "cardCss": css_content
            }
          }
        }

    dashboard = {
      "title": "RO Live Data Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for live RO Device Data (HTML Value Cards)",
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
