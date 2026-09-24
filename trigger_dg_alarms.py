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

def trigger_alarms():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    tenant_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    devices_to_alert = ["DG SET 1", "DG SET 2", "DG SET 3", "DG SET1", "DG SET2", "DG SET3", "DG Set 2", "DG Set 3"]
    
    for device_name in devices_to_alert:
        res = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName={device_name}", headers=tenant_headers)
        if res.status_code != 200:
            continue
        
        device_data = res.json()
        if not device_data or 'id' not in device_data:
            continue
            
        device_id = device_data['id']['id']
        
        alarm_payload = {
            "tenantId": {"entityType": "TENANT", "id": tenant_id},
            "type": "AI Predictive Alert",
            "originator": {"entityType": "DEVICE", "id": device_id},
            "severity": "CRITICAL",
            "status": "ACTIVE_UNACK",
            "details": {
                "description": f"AI predictive CRITICAL risk detected on {device_name}. Review summary and take recommended action.",
                "summary": "The generator is idle with 0 RPM and 0 kW power output. Oil pressure is critically low at 4 kPa. Coolant temp is normal at 39°C.",
                "severity": "CRITICAL",
                "health_score": 20,
                "failure_risk_pct": 85,
                "recommendation": "Check and restore oil pressure immediately.",
                "ai_mode": "openai",
                "message": "The generator is idle with 0 RPM and 0 kW power output. Oil pressure is critically low at 4 kPa. Coolant temp is normal at 39°C. | Action: Check and restore oil pressure immediately."
            }
        }
        
        res_alarm = requests.post(f"{BASE_URL}/api/alarm", json=alarm_payload, headers=tenant_headers)
        if res_alarm.status_code == 200:
            print(f"Triggered AI Predictive Alert for {device_name}")
        else:
            print(f"Failed to trigger alarm for {device_name}: {res_alarm.text}")

if __name__ == '__main__':
    trigger_alarms()
