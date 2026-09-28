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

def cleanup_duplicates():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # List of duplicate/redundant device names to remove
    duplicates_to_remove = [
        "Raspberry Pi LT Panels", # Duplicate of LT Panels Gateway
        "DG Set 2",              # Duplicate of DG SET2
        "DG Set 3"               # Duplicate of DG SET3
    ]

    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers).json()['data']
    for d in devices:
        name = d['name']
        d_id = d['id']['id']
        if name in duplicates_to_remove:
            res_del = requests.delete(f"{BASE_URL}/api/device/{d_id}", headers=tenant_headers)
            print(f"Removed duplicate device '{name}' (ID: {d_id}): Status {res_del.status_code}")

if __name__ == "__main__":
    cleanup_duplicates()
