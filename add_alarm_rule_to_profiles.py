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

def setup_alarms():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}

    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    tenant_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    res.raise_for_status()
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    
    profiles_to_update = ['woodward_kg1500', 'woodward_kg150']
    
    alarm_rule = {
        "id": "ai_predictive_alert_rule",
        "alarmType": "AI Predictive Alert",
        "createRules": {
            "CRITICAL": {
                "condition": {
                    "condition": [
                        {
                            "key": {
                                "type": "TIME_SERIES",
                                "key": "ai_risk_score"
                            },
                            "valueType": "NUMERIC",
                            "value": None,
                            "predicate": {
                                "type": "NUMERIC",
                                "operation": "GREATER_OR_EQUAL",
                                "value": {
                                    "defaultValue": 80.0,
                                    "userValue": None,
                                    "dynamicValue": None
                                }
                            }
                        }
                    ],
                    "spec": {
                        "type": "SIMPLE"
                    }
                },
                "schedule": None,
                "alarmDetails": "The generator is idle with 0 RPM and 0 kW power output. Oil pressure is critically low at 4 kPa. Coolant temp is normal at 39°C. | Action: Check and restore oil pressure immediately."
            }
        },
        "clearRule": {
            "condition": {
                "condition": [
                    {
                        "key": {
                            "type": "TIME_SERIES",
                            "key": "ai_risk_score"
                        },
                        "valueType": "NUMERIC",
                        "value": None,
                        "predicate": {
                            "type": "NUMERIC",
                            "operation": "LESS",
                            "value": {
                                "defaultValue": 80.0,
                                "userValue": None,
                                "dynamicValue": None
                            }
                        }
                    }
                ],
                "spec": {
                    "type": "SIMPLE"
                }
            },
            "schedule": None,
            "alarmDetails": None
        },
        "propagate": True,
        "propagateToOwner": False,
        "propagateToTenant": True,
        "propagateRelationTypes": None
    }
    
    for prof_name in profiles_to_update:
        profile = next((p for p in profiles if p['name'] == prof_name), None)
        if not profile:
            continue
            
        if 'profileData' not in profile or profile['profileData'] is None:
            profile['profileData'] = {}
            
        if 'alarms' not in profile['profileData'] or not profile['profileData']['alarms']:
            profile['profileData']['alarms'] = []
            
        # Remove existing if exists to avoid duplicates
        profile['profileData']['alarms'] = [a for a in profile['profileData']['alarms'] if a.get('id') != 'ai_predictive_alert_rule']
        
        profile['profileData']['alarms'].append(alarm_rule)
        
        print(f"Updating device profile {prof_name} with Alarm Rule...")
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=profile, headers=tenant_headers)
        if res.ok:
            print(f"Device Profile {prof_name} updated successfully!")
        else:
            print(f"Failed to update {prof_name}: {res.text}")

if __name__ == "__main__":
    setup_alarms()
