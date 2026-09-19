import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

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
            "entityAliasId": "dg-set-3-alias-uuid",
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

def setup_all():
    print("Logging into local ThingsBoard API as SysAdmin...")
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    print("Fetching Device 'DG Set 3'...")
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=DG Set 3", headers=tenant_headers).json()
    if not devices:
        print("Device 'DG Set 3' not found! Make sure it is provisioned.")
        return
    device_id = devices['id']['id']
    
    print(f"Device ID: {device_id}")
    
    dashboard = {
      "title": "DG Set 3 Live Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for DG Set 3 KPIs",
        "widgets": {
          "w1": create_widget("w1", 0, 0, "ambient_temp", "Temperature", "#f44336", "Ambient Temp", "°C"),
          "w2": create_widget("w2", 0, 8, "alarm_class_a", "Alarm A", "#ff9800", "Alarm Class A", ""),
          "w3": create_widget("w3", 0, 16, "alarm_class_b", "Alarm B", "#ff9800", "Alarm Class B", ""),
          "w4": create_widget("w4", 4, 0, "alarm_class_c", "Alarm C", "#ff9800", "Alarm Class C", ""),
          "w5": create_widget("w5", 4, 8, "alarm_class_d", "Alarm D", "#ff9800", "Alarm Class D", ""),
          "w6": create_widget("w6", 4, 16, "alarm_class_e", "Alarm E", "#ff9800", "Alarm Class E", ""),
          "w7": create_widget("w7", 8, 0, "alarm_class_f", "Alarm F", "#ff9800", "Alarm Class F", "")
        },
        "states": {
          "default": {
            "name": "DG Set 3 Overview",
            "root": True,
            "layouts": {
              "main": {
                "widgets": {
                  "w1": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 0},
                  "w2": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 8},
                  "w3": {"sizeX": 8, "sizeY": 4, "row": 0, "col": 16},
                  "w4": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 0},
                  "w5": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 8},
                  "w6": {"sizeX": 8, "sizeY": 4, "row": 4, "col": 16},
                  "w7": {"sizeX": 8, "sizeY": 4, "row": 8, "col": 0}
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
          "dg-set-3-alias-uuid": {
            "id": "dg-set-3-alias-uuid",
            "alias": "My DG Set 3",
            "filter": {
              "type": "singleEntity",
              "resolveMultiple": False,
              "singleEntity": {
                "entityType": "DEVICE",
                "id": device_id
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
      "name": "DG Set 3 Live Dashboard"
    }

    print("Pushing dashboard to ThingsBoard...")
    # Check if dashboard already exists
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if d['name'] == 'DG Set 3 Live Dashboard'), None)
    
    if target_dashboard:
        dashboard["id"] = target_dashboard["id"]
        dashboard["tenantId"] = target_dashboard["tenantId"]
        
    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard, headers=tenant_headers)
    if res.ok:
        print("Dashboard created/updated successfully!")
    else:
        print(f"Failed to push dashboard: {res.text}")

if __name__ == "__main__":
    setup_all()
