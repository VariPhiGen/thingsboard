import requests

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=1000&page=0", headers=tenant_headers).json()['data']
for d in devices:
    if d['name'].startswith('LT Panel Fire'):
        print(f"Deleting {d['name']}...")
        requests.delete(f"{BASE_URL}/api/device/{d['id']['id']}", headers=tenant_headers)
print("Done.")
