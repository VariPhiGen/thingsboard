import requests, json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": username, "password": password})
    res.raise_for_status()
    return res.json()['token']

try:
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
    
    # Get device
    res = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers)
    devices = res.json()['data']
    ro_device = next((d for d in devices if d['name'] == 'Live Python RO Device'), None)
    
    if not ro_device:
        print("Device not found")
        exit(1)
        
    dev_id = ro_device['id']['id']
    
    # Get device credentials (token)
    res = requests.get(f"{BASE_URL}/api/device/{dev_id}/credentials", headers=tenant_headers)
    creds = res.json()
    device_token = creds['credentialsId']
    print(f"Device Token: {device_token}")
    
    # Get device profile alarms
    profile_id = ro_device['deviceProfileId']['id']
    res = requests.get(f"{BASE_URL}/api/deviceProfile/{profile_id}", headers=tenant_headers)
    profile = res.json()
    
    print(json.dumps(profile.get('profileData', {}).get('alarms', []), indent=2))
    
except Exception as e:
    print(e)
