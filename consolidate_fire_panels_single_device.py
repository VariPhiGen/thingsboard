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

def create_card_widget(w_id, row, col, size_x, size_y, name, label, color, title, alias_id, unit=""):
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
        "showTitle": False,
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
                "decimals": 1,
                "usePostProcessing": True,
                "postFuncBody": "return (value === true || value === 'true') ? 'High Pressure' : 'Low Pressure';",
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
                "weight": "500",
                "style": "normal"
            }
        }
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

    res_single = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=LT Panel Fire", headers=tenant_headers)
    if res_single.ok and res_single.json():
        single_device = res_single.json()
        single_device['name'] = "Fire Suppression"
        single_device = requests.post(f"{BASE_URL}/api/device", json=single_device, headers=tenant_headers).json()
    else:
        res_single = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=Fire Suppression", headers=tenant_headers)
        if res_single.ok and res_single.json():
            single_device = res_single.json()
        else:
            dev_payload = {"name": "Fire Suppression", "type": "LT Panel Fire Profile"}
            single_device = requests.post(f"{BASE_URL}/api/device", json=dev_payload, headers=tenant_headers).json()

    single_device_id = single_device['id']['id']
    creds = requests.get(f"{BASE_URL}/api/device/{single_device_id}/credentials", headers=tenant_headers).json()
    master_token = creds['credentialsId']

    with open('/home/ubuntu/lt_panel_data_logger/fire_panel_token.txt', 'w') as f:
        f.write(master_token)

    print("Updating LT Panel Fire Profile with 3 Panel Alarm Rules...")
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    fire_profile = next((p for p in profiles if p['name'] == 'LT Panel Fire Profile'), None)

    fire_alarms = []
    for i in range(1, 4):
        # We can add alarms for low and high if we want. For simplicity, just high pressure alarm.
        fire_alarms.append(create_simple_alarm_rule(
            f"fire_panel_{i}_high_pressure_alarm", f"Fire Suppression {i} High Pressure",
            f"fire_panel_{i}_high_pressure", "GREATER_OR_EQUAL", "LESS", 100.0, "CRITICAL",
            f"High Pressure detected on Fire Suppression {i}!"
        ))
        fire_alarms.append(create_simple_alarm_rule(
            f"fire_panel_{i}_low_pressure_alarm", f"Fire Suppression {i} Low Pressure",
            f"fire_panel_{i}_low_pressure", "LESS", "GREATER_OR_EQUAL", 7.0, "WARNING",
            f"Low Pressure detected on Fire Suppression {i}!"
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

    print("Building Single Device 3-Panel Dashboard...")
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

    current_row = 0
    # Create 3 sets of cards
    for i in range(1, 4):
        # Fire Suppression i
        w_id = f"w_pressure_{i}"
        widgets[w_id] = create_card_widget(
            w_id, current_row, 0, 24, 4,
            f"cylinder_pressure_{i}", f"Fire Suppression {i}", "#03a9f4",
            "", alias_id, ""
        )
        main_widgets_layout[w_id] = {"sizeX": 24, "sizeY": 4, "row": current_row, "col": 0}
        
        current_row += 4

    dashboard_config = {
        "description": "Unified Single-Device 3-Panel Fire Suppression Dashboard",
        "widgets": widgets,
        "states": {
            "default": {
                "name": "Live Fire Suppression Overview",
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
    target_dashboard = next((d for d in dashboards if d['title'] == 'Fire Suppression'), None)

    dashboard_payload = {
        "title": "Fire Suppression",
        "configuration": dashboard_config
    }

    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]

    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("LT Panel Fire Dashboard successfully updated to 3 Fire Suppressions with value cards!")
    else:
        print(f"Failed to update dashboard: {res.text}")

if __name__ == "__main__":
    consolidate()
