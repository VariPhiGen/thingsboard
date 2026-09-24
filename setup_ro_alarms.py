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

def setup_alarms():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}

    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    tenants = res.json()['data']
    tenant_id = tenants[0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    res.raise_for_status()
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    
    # We will update the default device profile or create one for RO Device
    default_profile = next((p for p in profiles if p['name'] == 'default'), profiles[0])
    
    alarm_rule = {
        "id": "high_tds_alarm",
        "alarmType": "High TDS Alert",
        "createRules": {
            "CRITICAL": {
                "condition": {
                    "condition": [
                        {
                            "key": {
                                "type": "TIME_SERIES",
                                "key": "tds"
                            },
                            "valueType": "NUMERIC",
                            "value": None,
                            "predicate": {
                                "type": "NUMERIC",
                                "operation": "GREATER",
                                "value": {
                                    "defaultValue": 175.0,
                                    "userValue": None,
                                    "dynamicValue": {
                                        "sourceType": "CURRENT_DEVICE",
                                        "sourceAttribute": "highTdsThreshold",
                                        "inherit": True
                                    }
                                }
                            }
                        }
                    ],
                    "spec": {
                        "type": "SIMPLE"
                    }
                },
                "schedule": None,
                "alarmDetails": "TDS level is above 175"
            }
        },
        "clearRule": {
            "condition": {
                "condition": [
                    {
                        "key": {
                            "type": "TIME_SERIES",
                            "key": "tds"
                        },
                        "valueType": "NUMERIC",
                        "value": None,
                        "predicate": {
                            "type": "NUMERIC",
                            "operation": "LESS_OR_EQUAL",
                            "value": {
                                "defaultValue": 175.0,
                                "userValue": None,
                                "dynamicValue": {
                                    "sourceType": "CURRENT_DEVICE",
                                    "sourceAttribute": "highTdsThreshold",
                                    "inherit": True
                                }
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
    
    if 'profileData' not in default_profile:
        default_profile['profileData'] = {}
        
    if 'alarms' not in default_profile['profileData'] or not default_profile['profileData']['alarms']:
        default_profile['profileData']['alarms'] = []
        
    # Remove existing high tds alarm if exists
    default_profile['profileData']['alarms'] = [a for a in default_profile['profileData']['alarms'] if a.get('id') != 'high_tds_alarm']
    
    default_profile['profileData']['alarms'].append(alarm_rule)
    
    print("Updating device profile with Alarm Rule...")
    res = requests.post(f"{BASE_URL}/api/deviceProfile", json=default_profile, headers=tenant_headers)
    if res.ok:
        print("Device Profile Alarm Rule configured successfully!")
    else:
        print(f"Failed: {res.text}")

if __name__ == "__main__":
    setup_alarms()
