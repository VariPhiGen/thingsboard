import requests
import json
import os

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

PANEL_NAMES = [f"Fire Separation {i}" for i in range(1, 10)]

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def create_widget(w_id, row, col, size_x, size_y, name, label, color, title, alias_id, unit="psi"):
    return {
      "typeFullFqn": "system.cards.value_card",
      "type": "latest",
      "sizeX": size_x,
      "sizeY": size_y,
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
            "entityAliasId": alias_id,
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

def setup_fire_panels_and_dashboard():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # Fetch LT Panel Fire Profile
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    profile_id = next((p['id']['id'] for p in profiles if p['name'] == 'LT Panel Fire Profile'), None)
    if not profile_id:
        profile_id = next((p['id']['id'] for p in profiles if p['name'] == 'default'), None)

    device_map = {}
    tokens = {}

    print("Provisioning 9 Fire Separation Devices...")
    for dev_name in PANEL_NAMES:
        device_payload = {
            "name": dev_name,
            "type": "LT Panel Fire Profile",
            "deviceProfileId": {"id": profile_id, "entityType": "DEVICE_PROFILE"}
        }
        res = requests.post(f"{BASE_URL}/api/device", json=device_payload, headers=tenant_headers)
        if not res.ok:
            # Device already exists, fetch it
            res_dev = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName={dev_name}", headers=tenant_headers)
            device = res_dev.json()
        else:
            device = res.json()

        d_id = device['id']['id']
        device_map[dev_name] = d_id

        # Update profile assignment
        device['deviceProfileId'] = {"id": profile_id, "entityType": "DEVICE_PROFILE"}
        requests.post(f"{BASE_URL}/api/device", json=device, headers=tenant_headers)

        # Get Credentials
        creds = requests.get(f"{BASE_URL}/api/device/{d_id}/credentials", headers=tenant_headers).json()
        tokens[dev_name] = creds['credentialsId']
        print(f"Device: {dev_name} | ID: {d_id} | Token: {creds['credentialsId']}")

    # Save tokens to logger config file
    token_file = "/home/ubuntu/lt_panel_data_logger/fire_panel_tokens.json"
    with open(token_file, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"Saved device tokens to {token_file}")

    # Build Dashboard for all 9 Fire Panels
    print("Building 9-Panel Fire Separation Dashboard...")
    widgets = {}
    main_widgets_layout = {}
    entity_aliases = {}

    for idx, dev_name in enumerate(PANEL_NAMES):
        alias_id = f"fire-panel-alias-{idx+1}"
        d_id = device_map[dev_name]

        # Define Alias
        entity_aliases[alias_id] = {
            "id": alias_id,
            "alias": dev_name,
            "filter": {
                "type": "singleEntity",
                "resolveMultiple": False,
                "singleEntity": {
                    "entityType": "DEVICE",
                    "id": d_id
                }
            }
        }

        # Calculate grid positions (2 panels per row, 5 rows)
        row_num = (idx // 2) * 4
        col_offset = (idx % 2) * 12

        w_low_id = f"w_low_{idx+1}"
        w_high_id = f"w_high_{idx+1}"

        # Low Pressure Widget
        widgets[w_low_id] = create_widget(
            w_low_id, row_num, col_offset, 6, 4,
            "pressure_low", "Low Pressure", "#03a9f4",
            f"{dev_name} - Low Pressure", alias_id, "psi"
        )
        main_widgets_layout[w_low_id] = {"sizeX": 6, "sizeY": 4, "row": row_num, "col": col_offset}

        # High Pressure Widget
        widgets[w_high_id] = create_widget(
            w_high_id, row_num, col_offset + 6, 6, 4,
            "pressure_high", "High Pressure", "#f44336",
            f"{dev_name} - High Pressure", alias_id, "psi"
        )
        main_widgets_layout[w_high_id] = {"sizeX": 6, "sizeY": 4, "row": row_num, "col": col_offset + 6}

    dashboard_config = {
        "description": "Systematic 10-Panel LT Panel Fire Dashboard",
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
        "entityAliases": entity_aliases,
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
    }

    # Fetch existing dashboard to overwrite
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if d['name'] == 'LT Panel Fire Dashboard'), None)

    dashboard_payload = {
        "title": "LT Panel Fire Dashboard",
        "configuration": dashboard_config
    }

    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]

    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("LT Panel Fire Dashboard updated successfully with 9 panels!")
    else:
        print(f"Failed to update dashboard: {res.text}")

if __name__ == "__main__":
    setup_fire_panels_and_dashboard()
