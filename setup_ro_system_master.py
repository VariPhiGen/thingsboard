import requests
import json
import os

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

def create_widget(w_id, row, col, size_x, size_y, name, label, color, title, alias_id, unit=""):
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

def extract_id(entity_obj):
    if not entity_obj:
        return None
    id_field = entity_obj.get('id') if isinstance(entity_obj, dict) else entity_obj
    if isinstance(id_field, dict):
        return id_field.get('id')
    return id_field

def setup_ro_system():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # 1. Create/Update Profile: "RO System Profile"
    print("Creating/Updating RO System Profile...")
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    ro_profile = next((p for p in profiles if p['name'] == 'RO System Profile'), None)

    ro_alarms = [
        create_simple_alarm_rule(
            "high_tds_alarm", "High TDS Alert",
            "tds", "GREATER", "LESS_OR_EQUAL", 175.0, "CRITICAL",
            "High TDS level detected: ${tds} ppm (Threshold > 175 ppm)"
        ),
        create_simple_alarm_rule(
            "low_water_flow_alarm", "Low Water Flow Warning",
            "water_flow", "LESS", "GREATER_OR_EQUAL", 1.0, "WARNING",
            "Low Water Flow detected: ${water_flow} L/min (Threshold < 1.0 L/min)"
        ),
        create_simple_alarm_rule(
            "high_ro_pressure_alarm", "High RO Pressure Warning",
            "pressure", "GREATER", "LESS_OR_EQUAL", 65.0, "WARNING",
            "High RO System Pressure detected: ${pressure} psi (Threshold > 65 psi)"
        )
    ]

    if not ro_profile:
        ro_prof_payload = {
            "name": "RO System Profile",
            "type": "DEFAULT",
            "transportType": "DEFAULT",
            "provisionType": "DISABLED",
            "profileData": {
                "configuration": {"type": "DEFAULT"},
                "transportConfiguration": {"type": "DEFAULT"},
                "provisionConfiguration": {"type": "DISABLED", "provisionDeviceSecret": None},
                "alarms": ro_alarms
            }
        }
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=ro_prof_payload, headers=tenant_headers)
        if not res.ok:
            print("Error creating profile:", res.status_code, res.text)
        ro_profile = res.json()
    else:
        if 'profileData' not in ro_profile or not ro_profile['profileData']:
            ro_profile['profileData'] = {
                "configuration": {"type": "DEFAULT"},
                "transportConfiguration": {"type": "DEFAULT"},
                "provisionConfiguration": {"type": "DISABLED", "provisionDeviceSecret": None}
            }
        ro_profile['profileData']['alarms'] = ro_alarms
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=ro_profile, headers=tenant_headers)
        if not res.ok:
            print("Error updating profile:", res.status_code, res.text)
        ro_profile = res.json()

    ro_profile_id = extract_id(ro_profile)
    print(f"RO System Profile ID: {ro_profile_id}")

    # 2. Get/Create Master Device: "RO Plant System"
    print("Creating Master RO Device 'RO Plant System'...")
    res_ro = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=RO Plant System", headers=tenant_headers)
    if res_ro.ok and res_ro.text and res_ro.json():
        ro_device = res_ro.json()
    else:
        dev_payload = {
            "name": "RO Plant System",
            "type": "RO System Profile",
            "deviceProfileId": {"id": ro_profile_id, "entityType": "DEVICE_PROFILE"}
        }
        res_dev = requests.post(f"{BASE_URL}/api/device", json=dev_payload, headers=tenant_headers)
        if not res_dev.ok:
            print("Error creating device:", res_dev.status_code, res_dev.text)
        ro_device = res_dev.json()

    if ro_profile_id:
        ro_device['deviceProfileId'] = {"id": ro_profile_id, "entityType": "DEVICE_PROFILE"}
        res_dev_upd = requests.post(f"{BASE_URL}/api/device", json=ro_device, headers=tenant_headers)
        if not res_dev_upd.ok:
            print("Error updating device profile association:", res_dev_upd.status_code, res_dev_upd.text)
        ro_device = res_dev_upd.json()

    ro_device_id = extract_id(ro_device)
    print(f"RO Device ID: {ro_device_id}")

    creds_res = requests.get(f"{BASE_URL}/api/device/{ro_device_id}/credentials", headers=tenant_headers)
    if creds_res.ok:
        creds = creds_res.json()
        access_token = creds.get('credentialsId') or creds.get('credentialsValue') or str(creds)
    else:
        print("Error getting credentials:", creds_res.status_code, creds_res.text)
        access_token = ""

    print(f"\nMaster RO Device Name: RO Plant System")
    print(f"Master RO Device ID: {ro_device_id}")
    print(f"Master RO Access Token: {access_token}\n")

    token_file = "/home/ubuntu/lt_panel_data_logger/ro_token.txt"
    with open(token_file, "w") as f:
        f.write(access_token)
    print(f"Saved token to {token_file}")

    # 3. Create Dashboard: "RO Plant Dashboard"
    print("Building RO Plant Dashboard...")
    alias_id = "ro-plant-alias"
    entity_aliases = {
        alias_id: {
            "id": alias_id,
            "alias": "RO Plant System",
            "filter": {
                "type": "singleEntity",
                "resolveMultiple": False,
                "singleEntity": {
                    "entityType": "DEVICE",
                    "id": ro_device_id
                }
            }
        }
    }

    widgets = {
        "w_tds": create_widget("w_tds", 0, 0, 6, 4, "tds", "TDS Level", "#e91e63", "Water TDS Level", alias_id, "ppm"),
        "w_flow": create_widget("w_flow", 0, 6, 6, 4, "water_flow", "Water Flow Rate", "#00bcd4", "Permeate Flow Rate", alias_id, "L/min"),
        "w_pressure": create_widget("w_pressure", 0, 12, 6, 4, "pressure", "RO Pressure", "#ff9800", "RO System Pressure", alias_id, "psi"),
        "w_status": create_widget("w_status", 0, 18, 6, 4, "status", "Status", "#4caf50", "Operating Status", alias_id, "")
    }

    main_widgets_layout = {
        "w_tds": {"sizeX": 6, "sizeY": 4, "row": 0, "col": 0},
        "w_flow": {"sizeX": 6, "sizeY": 4, "row": 0, "col": 6},
        "w_pressure": {"sizeX": 6, "sizeY": 4, "row": 0, "col": 12},
        "w_status": {"sizeX": 6, "sizeY": 4, "row": 0, "col": 18}
    }

    dashboard_config = {
        "description": "Real-time Monitoring Dashboard for RO Plant System",
        "widgets": widgets,
        "states": {
            "default": {
                "name": "RO Plant Realtime Overview",
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
    target_dashboard = next((d for d in dashboards if 'RO' in d['title']), None)

    dashboard_payload = {
        "title": "RO Plant Dashboard",
        "configuration": dashboard_config
    }

    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]

    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("RO Plant Dashboard created/updated successfully!")
    else:
        print(f"Failed to update dashboard: {res.text}")

if __name__ == "__main__":
    setup_ro_system()
