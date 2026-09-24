import requests
BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'
def login():
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}, headers={"Accept": "application/json"})
    return res.json()['token']
sys_token = login()
sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
tenant_id = res.json()['data'][0]['id']['id']
res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
admin_user_id = res.json()['data'][0]['id']['id']
res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
tenant_token = res.json()['token']
tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

for name in ["DG Set 1", "DG Set 2", "DG Set 3", "DG SET1", "DG SET2", "DG SET3"]:
    res = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName={name}", headers=tenant_headers)
    if res.ok and res.json():
        device = res.json()
        if 'id' in device:
            profile_id = device.get('deviceProfileId', {}).get('id')
            res2 = requests.get(f"{BASE_URL}/api/deviceProfile/{profile_id}", headers=tenant_headers)
            profile_name = res2.json()['name']
            print(f"Device: {name} -> Profile: {profile_name}")
