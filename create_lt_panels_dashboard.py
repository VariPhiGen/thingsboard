import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

PANELS = [
    "EVM Charger",
    "Electrical room 1",
    "UPS Room 1",
    "Transformer 1",
    "Transformer 2",
    "Transformer 3",
    "Fire fighting wall"
]

def create_widget(w_id, row, col, name, label, color, title, unit=""):
    return {
      "typeFullFqn": "system.cards.value_card",
      "type": "latest",
      "sizeX": 6,
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
            "entityAliasId": "lt-panels-alias-uuid",
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
    
    print("Fetching LT Panels Gateway device...")
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=LT Panels Gateway", headers=tenant_headers).json()
    if 'id' not in devices:
        print("Device 'LT Panels Gateway' not found!")
        return
    device_id = devices['id']['id']
    
    widgets = {}
    main_widgets_layout = {}
    
    w_idx = 1
    row = 0
    for panel in PANELS:
        prefix = panel.replace(' ', '_')
        
        # Voltage
        w_id = f"w{w_idx}"
        widgets[w_id] = create_widget(w_id, row, 0, f"{prefix}_voltage", "Voltage", "#4caf50", f"{panel} Voltage", "V")
        main_widgets_layout[w_id] = {"sizeX": 6, "sizeY": 4, "row": row, "col": 0}
        w_idx += 1
        
        # Current
        w_id = f"w{w_idx}"
        widgets[w_id] = create_widget(w_id, row, 6, f"{prefix}_current", "Current", "#f44336", f"{panel} Current", "A")
        main_widgets_layout[w_id] = {"sizeX": 6, "sizeY": 4, "row": row, "col": 6}
        w_idx += 1
        
        # Power
        w_id = f"w{w_idx}"
        widgets[w_id] = create_widget(w_id, row, 12, f"{prefix}_power", "Power", "#ff9800", f"{panel} Power", "kW")
        main_widgets_layout[w_id] = {"sizeX": 6, "sizeY": 4, "row": row, "col": 12}
        w_idx += 1
        
        # Frequency
        w_id = f"w{w_idx}"
        widgets[w_id] = create_widget(w_id, row, 18, f"{prefix}_frequency", "Frequency", "#2196f3", f"{panel} Freq", "Hz")
        main_widgets_layout[w_id] = {"sizeX": 6, "sizeY": 4, "row": row, "col": 18}
        w_idx += 1
        
        row += 4

    dashboard_config = {
      "title": "LT Panels Dashboard",
      "image": None,
      "mobileHide": False,
      "mobileOrder": None,
      "configuration": {
        "description": "Dashboard for LT Panels Gateway",
        "widgets": widgets,
        "states": {
          "default": {
            "name": "Live LT Panels Overview",
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
          "lt-panels-alias-uuid": {
            "id": "lt-panels-alias-uuid",
            "alias": "LT Panels Gateway",
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
      "name": "LT Panels Dashboard"
    }

    print("Pushing Dashboard to ThingsBoard...")
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if d['name'] == 'LT Panels Dashboard'), None)
    
    dashboard_payload = {
        "title": "LT Panels Dashboard",
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
