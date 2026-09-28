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

def get_or_create_profile(tenant_headers, profile_name):
    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    profile = next((p for p in profiles if p['name'] == profile_name), None)
    if profile:
        return profile
    
    # Create new profile
    new_prof_payload = {
        "name": profile_name,
        "type": "DEFAULT",
        "transportType": "DEFAULT",
        "provisionType": "DISABLED",
        "profileData": {
            "configuration": {"type": "DEFAULT"},
            "transportConfiguration": {"type": "DEFAULT"},
            "alarms": []
        }
    }
    res = requests.post(f"{BASE_URL}/api/deviceProfile", json=new_prof_payload, headers=tenant_headers)
    res.raise_for_status()
    print(f"Created new Device Profile: {profile_name}")
    return res.json()

def setup_all():
    print("Logging in...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # 1. LT Panel Fire Profile
    fire_profile = get_or_create_profile(tenant_headers, "LT Panel Fire Profile")
    fire_alarms = [
        create_simple_alarm_rule(
            "fire_high_pressure_alarm", "Fire System High Pressure",
            "pressure_high", "GREATER", "LESS_OR_EQUAL", 100.0, "CRITICAL",
            "High Pressure Alarm detected on Fire Panel: ${pressure_high} bar (Threshold: > 100 bar)"
        ),
        create_simple_alarm_rule(
            "fire_low_pressure_alarm", "Fire System Low Pressure",
            "pressure_low", "LESS", "GREATER_OR_EQUAL", 7.0, "WARNING",
            "Low Pressure Warning detected on Fire Panel: ${pressure_low} bar (Threshold: < 7 bar)"
        )
    ]
    if 'profileData' not in fire_profile or not fire_profile['profileData']:
        fire_profile['profileData'] = {}
    fire_profile['profileData']['alarms'] = fire_alarms
    res = requests.post(f"{BASE_URL}/api/deviceProfile", json=fire_profile, headers=tenant_headers)
    print(f"Updated LT Panel Fire Profile: {res.status_code}")

    # 2. LT Panels Profile (8 Panels)
    lt_panels_profile = get_or_create_profile(tenant_headers, "LT Panels Profile")
    panels = [
        ("EVM Charger", "EVM_Charger"),
        ("Electrical Room 1", "Electrical_room_1"),
        ("UPS Room 1", "UPS_Room_1"),
        ("Transformer 1", "Transformer_1"),
        ("Transformer 2", "Transformer_2"),
        ("UPS Panel 2", "UPS_Panel_2"),
        ("Transformer 3", "Transformer_3"),
        ("Fire Fighting Wall", "Fire_fighting_wall")
    ]
    lt_alarms = []
    for label, prefix in panels:
        # High Voltage > 238.5V
        lt_alarms.append(create_simple_alarm_rule(
            f"{prefix}_high_voltage_alarm", f"{label} High Voltage",
            f"{prefix}_voltage", "GREATER", "LESS_OR_EQUAL", 238.5, "CRITICAL",
            f"High Voltage detected on {label}: ${{ {prefix}_voltage }} V (Threshold: > 238.5 V)"
        ))
        # High Current / Overcurrent > 85.0 A
        lt_alarms.append(create_simple_alarm_rule(
            f"{prefix}_overcurrent_alarm", f"{label} Overcurrent",
            f"{prefix}_current", "GREATER", "LESS_OR_EQUAL", 85.0, "CRITICAL",
            f"High Current Overload detected on {label}: ${{ {prefix}_current }} A (Threshold: > 85.0 A)"
        ))

    if 'profileData' not in lt_panels_profile or not lt_panels_profile['profileData']:
        lt_panels_profile['profileData'] = {}
    lt_panels_profile['profileData']['alarms'] = lt_alarms
    res = requests.post(f"{BASE_URL}/api/deviceProfile", json=lt_panels_profile, headers=tenant_headers)
    print(f"Updated LT Panels Profile: {res.status_code}")

    # 3. DG Set Profiles (woodward_kg1500 & woodward_kg150)
    dg_alarms = [
        create_simple_alarm_rule(
            "high_coolant_temp_alarm", "High Coolant Temp",
            "coolant_temp", "GREATER", "LESS_OR_EQUAL", 90.0, "CRITICAL",
            "High Coolant Temperature detected: ${coolant_temp} °C (Threshold: > 90 °C)"
        ),
        create_simple_alarm_rule(
            "low_oil_pressure_alarm", "Low Oil Pressure",
            "oil_pressure", "LESS", "GREATER_OR_EQUAL", 100.0, "CRITICAL",
            "Low Oil Pressure detected: ${oil_pressure} kPa (Threshold: < 100 kPa)"
        ),
        create_simple_alarm_rule(
            "high_engine_rpm_alarm", "Engine Overspeed",
            "engine_rpm", "GREATER", "LESS_OR_EQUAL", 1800.0, "CRITICAL",
            "Engine Overspeed detected: ${engine_rpm} RPM (Threshold: > 1800 RPM)"
        ),
        create_simple_alarm_rule(
            "low_fuel_level_alarm", "Low Fuel Level",
            "fuel_level", "LESS", "GREATER_OR_EQUAL", 15.0, "WARNING",
            "Low Fuel Level warning: ${fuel_level} % (Threshold: < 15 %)"
        ),
        create_simple_alarm_rule(
            "low_battery_voltage_alarm", "Low Battery Voltage",
            "battery_voltage", "LESS", "GREATER_OR_EQUAL", 11.5, "WARNING",
            "Low Battery Voltage detected: ${battery_voltage} V (Threshold: < 11.5 V)"
        )
    ]

    for prof_name in ["woodward_kg1500", "woodward_kg150"]:
        prof = get_or_create_profile(tenant_headers, prof_name)
        if 'profileData' not in prof or not prof['profileData']:
            prof['profileData'] = {}
        
        # Keep existing custom/AI alarms and add our rules
        existing = [a for a in prof['profileData'].get('alarms', []) if a.get('id') not in [x['id'] for x in dg_alarms]]
        prof['profileData']['alarms'] = existing + dg_alarms
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=prof, headers=tenant_headers)
        print(f"Updated DG Profile {prof_name}: {res.status_code}")

    # Assign Devices to proper Profiles
    device_assignments = {
        "LT Panel Fire": "LT Panel Fire Profile",
        "LT Panels Gateway": "LT Panels Profile",
        "Raspberry Pi LT Panels": "LT Panels Profile",
        "DG SET1": "woodward_kg1500",
        "DG Set 1": "woodward_kg1500",
        "DG SET2": "woodward_kg1500",
        "DG Set 2": "woodward_kg1500",
        "DG SET3": "woodward_kg150",
        "DG Set 3": "woodward_kg150"
    }

    all_profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    prof_map = {p['name']: p['id']['id'] for p in all_profiles}

    for dev_name, prof_name in device_assignments.items():
        res = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName={dev_name}", headers=tenant_headers)
        if res.ok and res.json():
            device = res.json()
            p_id = prof_map.get(prof_name)
            if p_id:
                device['deviceProfileId'] = {"id": p_id, "entityType": "DEVICE_PROFILE"}
                update_res = requests.post(f"{BASE_URL}/api/device", json=device, headers=tenant_headers)
                print(f"Assigned Device '{dev_name}' -> Profile '{prof_name}': {update_res.status_code}")

if __name__ == "__main__":
    setup_all()
