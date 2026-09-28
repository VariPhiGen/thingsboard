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

def fix_dg3():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    dg1 = requests.get(f"{BASE_URL}/api/device/3877b730-81cb-11f1-a760-b3ba4cbe1b98", headers=tenant_headers).json()
    correct_profile_id = dg1['deviceProfileId']

    res = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=DG SET3", headers=tenant_headers)
    if res.ok and res.json():
        dg3 = res.json()
        dg3['deviceProfileId'] = correct_profile_id
        dg3['type'] = 'woodward_kg1500'
        dg3['additionalInfo'] = {'gateway': False}

        upd = requests.post(f"{BASE_URL}/api/device", json=dg3, headers=tenant_headers)
        if upd.ok:
            print("DG SET3 successfully configured as master device with profile woodward_kg1500!")

if __name__ == "__main__":
    fix_dg3()
