import requests
import time

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def sync_dg1_state():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    now_ts = int(time.time() * 1000)

    # 1. Clear legacy gateway proxy flags on DG SET1
    dg1 = requests.get(f"{BASE_URL}/api/device/3877b730-81cb-11f1-a760-b3ba4cbe1b98", headers=tenant_headers).json()
    dg1['additionalInfo'] = {'gateway': False}
    requests.post(f"{BASE_URL}/api/device", json=dg1, headers=tenant_headers)

    # 2. Reset connection attributes so activity is driven 100% by real physical Modbus telemetry
    requests.post(
        f"{BASE_URL}/api/plugins/telemetry/DEVICE/3877b730-81cb-11f1-a760-b3ba4cbe1b98/SERVER_SCOPE",
        json={'lastDisconnectTime': now_ts, 'active': False},
        headers=tenant_headers
    )
    print("DG SET1 connection state synchronized with real hardware telemetry requirements.")

if __name__ == "__main__":
    sync_dg1_state()
