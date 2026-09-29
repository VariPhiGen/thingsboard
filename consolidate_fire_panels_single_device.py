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

def create_widget(w_id, row, col, size_x, size_y, name, label, color, title, alias_id, unit="", typeFullFqn="system.cards.value_card"):
    return {
      "typeFullFqn": typeFullFqn,
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
                "decimals": 0,
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
            "minValue": 0,
            "maxValue": 1,
            "majorTicksCount": 1,
            "minorTicks": 0,
            "highlights": [
                {"from": 0, "to": 0.5, "color": "rgba(0, 255, 0, .3)"},
                {"from": 0.5, "to": 1, "color": "rgba(255, 0, 0, .3)"}
            ]
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
    else:
        dev_payload = {"name": "LT Panel Fire", "type": "LT Panel Fire Profile"}
        single_device = requests.post(f"{BASE_URL}/api/device", json=dev_payload, headers=tenant_headers).json()

    single_device_id = single_device['id']['id']
    creds = requests.get(f"{BASE_URL}/api/device/{single_device_id}/credentials", headers=tenant_headers).json()
    master_token = creds['credentialsId']

    with open('/home/ubuntu/lt_panel_data_logger/fire_panel_token.txt', 'w') as f:
        f.write(master_token)

    print("Updating LT Panel Fire Profile with 9 Panel Alarm Rules...")
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    fire_profile = next((p for p in profiles if p['name'] == 'LT Panel Fire Profile'), None)

    fire_alarms = []
    for i in range(1, 10):
        fire_alarms.append(create_simple_alarm_rule(
            f"fire_panel_{i}_pressure_alarm", f"Fire Separation {i} High Pressure",
            f"fire_panel_{i}_pressure", "EQUAL", "NOT_EQUAL", 1.0, "CRITICAL",
            f"High Pressure detected on Fire Separation {i}!"
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

    print("Building Single Device 9-Panel Dashboard...")
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

    for i in range(1, 10):
        idx = i - 1
        row_num = (idx // 3) * 6
        col_offset = (idx % 3) * 8

        w_id = f"w_gauge_{i}"

        # Single pressure gauge
        widgets[w_id] = create_widget(
            w_id, row_num, col_offset, 8, 6,
            f"fire_panel_{i}_pressure", "0=Low, 1=High", "#03a9f4",
            f"Fire Separation {i}", alias_id, "",
            "system.analogue_gauges.radial_gauge_canvas_gauges"
        )
        main_widgets_layout[w_id] = {"sizeX": 8, "sizeY": 6, "row": row_num, "col": col_offset}

    dashboard_config = {
        "description": "Unified Single-Device 9-Panel Fire Separation Dashboard",
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
