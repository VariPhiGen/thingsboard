import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def create_widget(w_id, row, col, name, label, color, title, unit=""):
    return {
      "typeFullFqn": "system.cards.value_card",
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
            "entityAliasId": "fire-panel-alias-uuid",
            "dataKeys": [
              {
                "name": name,
                "type": "timeseries",
                "label": label,
                "color": color,
                "units": unit,
                "decimals": 2,
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

def generate_dashboard():
    print("Logging into ThingsBoard...")
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    print("Fetching LT Panel Fire device...")
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=LT Panel Fire", headers=tenant_headers).json()
    if 'id' not in devices:
        print("Device 'LT Panel Fire' not found!")
        return
    device_id = devices['id']['id']
    
    widgets = {}
    main_widgets_layout = {}
    
    # Widget for pressure_low
    widgets["w1"] = create_widget("w1", 0, 0, "pressure_low", "Low Pressure", "#03a9f4", "Low Pressure", "psi")
    main_widgets_layout["w1"] = {"sizeX": 8, "sizeY": 4, "row": 0, "col": 0}
    
    # Widget for pressure_high
    widgets["w2"] = create_widget("w2", 0, 8, "pressure_high", "High Pressure", "#f44336", "High Pressure", "psi")
    main_widgets_layout["w2"] = {"sizeX": 8, "sizeY": 4, "row": 0, "col": 8}

    dashboard_config = {
      "title": "LT Panel Fire Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for LT Panel Fire Gateway",
        "widgets": widgets,
        "states": {
          "default": {
            "name": "Live Fire Panel Overview",
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
          "fire-panel-alias-uuid": {
            "id": "fire-panel-alias-uuid",
            "alias": "LT Panel Fire",
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
      "name": "LT Panel Fire Dashboard"
    }

    print("Pushing Dashboard to ThingsBoard...")
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if d['name'] == 'LT Panel Fire Dashboard'), None)
    
    dashboard_payload = {
        "title": "LT Panel Fire Dashboard",
        "configuration": dashboard_config.get("configuration", {})
    }
    
    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]
        
    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("Dashboard created/updated successfully!")
    else:
        print(f"Failed to push dashboard: {res.text}")

if __name__ == "__main__":
    generate_dashboard()
