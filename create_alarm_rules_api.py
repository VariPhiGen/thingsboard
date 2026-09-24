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

def create_alarm_rule():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    tenant_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    # Get device profile woodward_kg1500
    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    profile_1500 = next((p for p in profiles if p['name'] == 'woodward_kg1500'), None)
    profile_150 = next((p for p in profiles if p['name'] == 'woodward_kg150'), None)

    for profile in [profile_1500, profile_150]:
        if not profile:
            continue
            
        profile_id = profile['id']['id']
        
        rule_payload = {
            "entityId": {
              "entityType": "DEVICE_PROFILE",
              "id": profile_id
            },
            "name": "AI Predictive Alert",
            "debugSettings": {
              "failuresEnabled": True,
              "allEnabled": False,
              "allEnabledUntil": 0
            },
            "configurationVersion": 0,
            "configuration": {
              "type": "ALARM",
              "arguments": {
                "ai_risk_score": {
                  "refEntityKey": {
                    "key": "ai_risk_score",
                    "type": "TS_LATEST"
                  }
                }
              },
              "createRules": {
                "CRITICAL": {
                  "condition": {
                    "type": "SIMPLE",
                    "expression": {
                      "type": "SIMPLE",
                      "filters": [
                        {
                          "argument": "ai_risk_score",
                          "valueType": "NUMERIC",
                          "operation": None,
                          "predicates": [
                            {
                              "type": "NUMERIC",
                              "operation": "GREATER",
                              "value": {
                                "staticValue": 80.0,
                                "dynamicValueArgument": None
                              }
                            }
                          ]
                        }
                      ],
                      "operation": "AND"
                    },
                    "schedule": None
                  },
                  "alarmDetails": "AI predictive CRITICAL risk detected. Health score ${ai_risk_score}",
                  "dashboardId": None
                }
              },
              "clearRule": {
                "condition": {
                  "type": "SIMPLE",
                  "expression": {
                    "type": "SIMPLE",
                    "filters": [
                      {
                        "argument": "ai_risk_score",
                        "valueType": "NUMERIC",
                        "operation": None,
                        "predicates": [
                          {
                            "type": "NUMERIC",
                            "operation": "LESS_OR_EQUAL",
                            "value": {
                              "staticValue": 80.0,
                              "dynamicValueArgument": None
                            }
                          }
                        ]
                      }
                    ],
                    "operation": "AND"
                  },
                  "schedule": None
                },
                "alarmDetails": "AI risk lowered",
                "dashboardId": None
              },
              "propagate": False,
              "propagateToOwner": False,
              "propagateToTenant": False,
              "propagateRelationTypes": None,
              "output": None
            },
            "additionalInfo": None
        }

        print(f"Creating CalculatedFieldAlarmRule for {profile['name']}...")
        res = requests.post(f"{BASE_URL}/api/alarm/rule", json=rule_payload, headers=tenant_headers)
        if res.ok:
            print(f"Success for {profile['name']}!")
        else:
            print(f"Failed for {profile['name']}: {res.text}")

if __name__ == '__main__':
    create_alarm_rule()
