import requests

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

MASTER_DEVICES = [
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

def purge_non_master_devices():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    while True:
        res = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=1000&page=0", headers=tenant_headers)
        if not res.ok:
            break
        data = res.json().get('data', [])
        to_del = [d for d in data if d['name'] not in MASTER_DEVICES]
        if not to_del:
            print("Zero non-master devices remaining!")
            break

        print(f"Found {len(to_del)} non-master devices to delete...")
        for d in to_del:
            d_id = d['id']['id']
            res_del = requests.delete(f"{BASE_URL}/api/device/{d_id}", headers=tenant_headers)
            print(f"Deleted '{d['name']}' ({d_id}): Status {res_del.status_code}")

    # Final list
    res_final = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=1000&page=0", headers=tenant_headers)
    final_devices = res_final.json().get('data', [])
    print(f"\n==========================================")
    print(f"FINAL MASTER DEVICES IN THINGSBOARD ({len(final_devices)}):")
    for d in final_devices:
        print(f"  ✔ {d['name']}")
    print(f"==========================================")

if __name__ == "__main__":
    purge_non_master_devices()
