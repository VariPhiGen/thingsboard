import requests

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def create_alarm_rule_dict(alarm_id, alarm_type, key, operation, clear_operation, default_val, dynamic_attr, severity, message):
    dynamic_val = {
        "sourceType": "CURRENT_DEVICE",
        "sourceAttribute": dynamic_attr,
        "inherit": True
    }
    
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
                                    "dynamicValue": dynamic_val
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
                                "dynamicValue": dynamic_val
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

def setup_alarms():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}

    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    tenant_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    
    profiles_to_update = ['woodward_kg1500', 'woodward_kg150']
    
    new_alarms = [
        create_alarm_rule_dict("high_coolant_temp_alarm", "High Coolant Temp", "coolant_temp", "GREATER", "LESS_OR_EQUAL", 95.0, "coolantTempThreshold", "CRITICAL", "High Coolant Temperature detected"),
        create_alarm_rule_dict("low_oil_pressure_alarm", "Low Oil Pressure", "oil_pressure", "LESS", "GREATER_OR_EQUAL", 100.0, "lowOilPressureThreshold", "CRITICAL", "Low Oil Pressure detected"),
        create_alarm_rule_dict("high_engine_rpm_alarm", "Engine Overspeed", "engine_rpm", "GREATER", "LESS_OR_EQUAL", 1800.0, "engineOverspeedThreshold", "CRITICAL", "Engine Overspeed detected"),
        create_alarm_rule_dict("low_fuel_level_alarm", "Low Fuel Level", "fuel_level", "LESS", "GREATER_OR_EQUAL", 15.0, "lowFuelLevelThreshold", "WARNING", "Low Fuel Level warning"),
        create_alarm_rule_dict("low_battery_voltage_alarm", "Low Battery Voltage", "battery_voltage", "LESS", "GREATER_OR_EQUAL", 11.5, "lowBatteryVoltageThreshold", "WARNING", "Low Battery Voltage detected")
    ]
    
    alarm_ids = [a['id'] for a in new_alarms]
    
    for prof_name in profiles_to_update:
        profile = next((p for p in profiles if p['name'] == prof_name), None)
        if not profile:
            continue
            
        if 'profileData' not in profile or profile['profileData'] is None:
            profile['profileData'] = {}
            
        if 'alarms' not in profile['profileData'] or not profile['profileData']['alarms']:
            profile['profileData']['alarms'] = []
            
        # Keep existing alarms that are not in our new batch
        existing_alarms = [a for a in profile['profileData']['alarms'] if a.get('id') not in alarm_ids]
        
        # Add new alarms
        profile['profileData']['alarms'] = existing_alarms + new_alarms
        
        print(f"Updating device profile {prof_name} with new Alarm Rules...")
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=profile, headers=tenant_headers)
        if res.ok:
            print(f"Device Profile {prof_name} updated successfully!")
        else:
            print(f"Failed to update {prof_name}: {res.text}")

if __name__ == "__main__":
    setup_alarms()
