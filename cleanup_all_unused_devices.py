import requests

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

MASTER_DEVICES_TO_KEEP = [
    "LT Panel Fire",
    "LT Panels Gateway",
    "DG SET1",
    "DG SET2",
    "DG SET3"
]

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def clean_all_unused():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # Page loop to find and delete all non-master devices
    page = 0
    deleted_count = 0
    while True:
        res = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page={page}", headers=tenant_headers)
        if not res.ok:
            break
        devices = res.json().get('data', [])
        if not devices:
            break

        to_delete = [d for d in devices if d['name'] not in MASTER_DEVICES_TO_KEEP]
        if not to_delete:
            page += 1
            if page > 5:
                break
            continue

        for d in to_delete:
            name = d['name']
            d_id = d['id']['id']
            res_del = requests.delete(f"{BASE_URL}/api/device/{d_id}", headers=tenant_headers)
            if res_del.ok:
                print(f"Deleted unused device '{name}' (ID: {d_id})")
                deleted_count += 1
            else:
                print(f"Failed to delete '{name}': {res_del.text}")

    print(f"\nClean up complete! Total deleted unused devices: {deleted_count}")

if __name__ == "__main__":
    clean_all_unused()
