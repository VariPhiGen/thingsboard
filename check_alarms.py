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

def check():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    tenant_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    admin_user_id = res.json()['data'][0]['id']['id']

    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    # Get device ID
    res = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=Smart RO Purifier", headers=tenant_headers)
    devices = res.json()
    if not devices:
        print("Device not found")
        return
    device_id = devices['id']['id']
    print(f"Checking alarms for device {device_id}...")
    
    # Check alarms
    res = requests.get(f"{BASE_URL}/api/alarm/DEVICE/{device_id}?pageSize=10&page=0", headers=tenant_headers)
    alarms = res.json()['data']
    if alarms:
        for a in alarms:
            print(f"Found Alarm: {a.get('type')} - {a.get('status')} - {a.get('severity')}")
    else:
        print("No alarms found for this device")

if __name__ == '__main__':
    check()
