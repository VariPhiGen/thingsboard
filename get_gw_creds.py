import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def get_creds():
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers).json()['data']
    
    for device in devices:
        if device.get('additionalInfo', {}).get('gateway', False):
            print(f"Gateway Device found: {device['name']}")
            device_id = device['id']['id']
            res = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers)
            print(json.dumps(res.json(), indent=2))

if __name__ == "__main__":
    get_creds()
