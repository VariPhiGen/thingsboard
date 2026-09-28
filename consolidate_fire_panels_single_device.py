import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def create_simple_alarm_rule(alarm_id, alarm_type, key, operation, clear_operation, default_val, severity, message):
    return {
        "id": alarm_id,
        "alarmType": alarm_type,
        "createRules": {
            severity: {
                "condition": {
                    "condition": [
                        {
                            "key": {"type": "TIME_SERIES", "key": key},
                            "valueType": "NUMERIC",
                            "predicate": {
                                "type": "NUMERIC",
                                "operation": operation,
                                "value": {
                                    "defaultValue": default_val,
                                    "userValue": None,
                                    "dynamicValue": None
                                }
                            }
                        }
                    ],
                    "spec": {"type": "SIMPLE"}
                },
                "alarmDetails": message
            }
        },
        "clearRule": {
            "condition": {
                "condition": [
                    {
                        "key": {"type": "TIME_SERIES", "key": key},
                        "valueType": "NUMERIC",
                        "predicate": {
                            "type": "NUMERIC",
                            "operation": clear_operation,
                            "value": {
                                "defaultValue": default_val,
                                "userValue": None,
                                "dynamicValue": None
                            }
                        }
                    }
                ],
                "spec": {"type": "SIMPLE"}
            }
        },
        "propagate": True,
        "propagateToTenant": True
    }

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

def consolidate():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # 1. Delete individual devices (LT Panel Fire 01 .. 10)
    print("Cleaning up individual devices from Devices list...")
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers).json()['data']
    for d in devices:
        name = d['name']
        if name.startswith("LT Panel Fire ") and name != "LT Panel Fire":
            d_id = d['id']['id']
            res_del = requests.delete(f"{BASE_URL}/api/device/{d_id}", headers=tenant_headers)
            print(f"Deleted individual device '{name}': {res_del.status_code}")

    # 2. Get/Create Single Master Device: "LT Panel Fire"
    res_single = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=LT Panel Fire", headers=tenant_headers)
    if res_single.ok and res_single.json():
        single_device = res_single.json()
    else:
        # Create single master device
        dev_payload = {"name": "LT Panel Fire", "type": "LT Panel Fire Profile"}
        single_device = requests.post(f"{BASE_URL}/api/device", json=dev_payload, headers=tenant_headers).json()

    single_device_id = single_device['id']['id']
    creds = requests.get(f"{BASE_URL}/api/device/{single_device_id}/credentials", headers=tenant_headers).json()
    master_token = creds['credentialsId']

    print(f"\nMaster Device 'LT Panel Fire' ID: {single_device_id}")
    print(f"Master Device Access Token: {master_token}\n")

    # Save token to file
    with open('/home/ubuntu/lt_panel_data_logger/fire_panel_token.txt', 'w') as f:
        f.write(master_token)

    # 3. Create/Update Profile with 10 Panel Alarm Rules
    print("Updating LT Panel Fire Profile with 10 Panel Alarm Rules...")
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    fire_profile = next((p for p in profiles if p['name'] == 'LT Panel Fire Profile'), None)

    fire_alarms = []
    for i in range(1, 11):
        # High Pressure > 100 bar
        fire_alarms.append(create_simple_alarm_rule(
            f"fire_panel_{i}_high_pressure_alarm", f"Fire Panel {i:02d} High Pressure",
            f"fire_panel_{i}_pressure_high", "GREATER", "LESS_OR_EQUAL", 100.0, "CRITICAL",
            f"High Pressure detected on Fire Panel {i:02d}: ${{ fire_panel_{i}_pressure_high }} psi (Threshold > 100 psi)"
        ))
        # Low Pressure < 7 bar
        fire_alarms.append(create_simple_alarm_rule(
            f"fire_panel_{i}_low_pressure_alarm", f"Fire Panel {i:02d} Low Pressure",
            f"fire_panel_{i}_pressure_low", "LESS", "GREATER_OR_EQUAL", 7.0, "WARNING",
            f"Low Pressure warning detected on Fire Panel {i:02d}: ${{ fire_panel_{i}_pressure_low }} psi (Threshold < 7 psi)"
        ))

    if not fire_profile:
        fire_profile_payload = {
            "name": "LT Panel Fire Profile",
            "type": "DEFAULT",
            "profileData": {"alarms": fire_alarms}
        }
        fire_profile = requests.post(f"{BASE_URL}/api/deviceProfile", json=fire_profile_payload, headers=tenant_headers).json()
    else:
        if 'profileData' not in fire_profile or not fire_profile['profileData']:
            fire_profile['profileData'] = {}
        fire_profile['profileData']['alarms'] = fire_alarms
        fire_profile = requests.post(f"{BASE_URL}/api/deviceProfile", json=fire_profile, headers=tenant_headers).json()

    p_id = fire_profile['id']['id']
    single_device['deviceProfileId'] = {"id": p_id, "entityType": "DEVICE_PROFILE"}
    requests.post(f"{BASE_URL}/api/device", json=single_device, headers=tenant_headers)

    # 4. Update LT Panel Fire Dashboard to display 10 Panels mapped to the Single Device
    print("Building Single Device 10-Panel Dashboard...")
    alias_id = "single-fire-device-alias"
    entity_aliases = {
        alias_id: {
            "id": alias_id,
            "alias": "LT Panel Fire Gateway",
            "filter": {
                "type": "singleEntity",
                "resolveMultiple": False,
                "singleEntity": {
                    "entityType": "DEVICE",
                    "id": single_device_id
                }
            }
        }
    }

    widgets = {}
    main_widgets_layout = {}

    for i in range(1, 11):
        idx = i - 1
        row_num = (idx // 2) * 4
        col_offset = (idx % 2) * 12

        w_low_id = f"w_low_{i}"
        w_high_id = f"w_high_{i}"

        # Low pressure widget
        widgets[w_low_id] = create_widget(
            w_low_id, row_num, col_offset, 6, 4,
            f"fire_panel_{i}_pressure_low", "Low Pressure", "#03a9f4",
            f"LT Panel Fire {i:02d} - Low Pressure", alias_id, "psi"
        )
        main_widgets_layout[w_low_id] = {"sizeX": 6, "sizeY": 4, "row": row_num, "col": col_offset}

        # High pressure widget
        widgets[w_high_id] = create_widget(
            w_high_id, row_num, col_offset + 6, 6, 4,
            f"fire_panel_{i}_pressure_high", "High Pressure", "#f44336",
            f"LT Panel Fire {i:02d} - High Pressure", alias_id, "psi"
        )
        main_widgets_layout[w_high_id] = {"sizeX": 6, "sizeY": 4, "row": row_num, "col": col_offset + 6}

    dashboard_config = {
        "description": "Unified Single-Device 10-Panel LT Panel Fire Dashboard",
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
        print("LT Panel Fire Dashboard successfully consolidated into 1 Master Device!")
    else:
        print(f"Failed to update dashboard: {res.text}")

if __name__ == "__main__":
    consolidate()
