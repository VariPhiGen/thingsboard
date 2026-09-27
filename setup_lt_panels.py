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

def setup():
    print("Logging in as SysAdmin...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}

    print("Fetching existing tenants...")
    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    tenants = res.json()['data']
    
    if not tenants:
        print("No tenants found! Creating a new one...")
        tenant_payload = {"title": "RO Tenant", "region": "Global"}
        res = requests.post(f"{BASE_URL}/api/tenant", json=tenant_payload, headers=sys_headers)
        res.raise_for_status()
        tenant_id = res.json()['id']['id']
    else:
        tenant_id = tenants[0]['id']['id']
        print(f"Using existing Tenant ID: {tenant_id}")

    print("Fetching Tenant Admin users...")
    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    res.raise_for_status()
    users = res.json()['data']
    
    if not users:
        print("Creating a mock user payload for tenant...")
        return

    admin_user_id = users[0]['id']['id']
    admin_email = users[0]['email']
    print(f"Using Tenant Admin: {admin_email}")

    print("Generating Tenant Admin Token...")
    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    res.raise_for_status()
    tenant_token = res.json()['token']
    
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    print("Fetching Device Profiles...")
    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    profile_id = next((p['id']['id'] for p in profiles if p['name'] == 'default'), None)
    
    if not profile_id:
        print("Could not find 'default' profile.")
        return
    else:
        print(f"Using existing default profile ID: {profile_id}")

    device_name = "LT Panels Gateway"
    print(f"Creating Device: {device_name}...")
    device_payload = {
        "name": device_name,
        "type": "default",
        "deviceProfileId": {"id": profile_id, "entityType": "DEVICE_PROFILE"}
    }
    res = requests.post(f"{BASE_URL}/api/device", json=device_payload, headers=tenant_headers)
    
    device_id = None
    if not res.ok:
        if "already exists" in res.text:
            print("Device already exists. Fetching its ID...")
            res_dev = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName={device_name}", headers=tenant_headers)
            if res_dev.ok:
                device = res_dev.json()
                device_id = device['id']['id']
            else:
                print(f"Failed to fetch existing device: {res_dev.text}")
                return
        else:
            print(f"Failed to create device: {res.text}")
            return
    else:
        device = res.json()
        device_id = device['id']['id']
    
    print("Getting Device Token...")
    res = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers)
    access_token = res.json()['credentialsId']

    print(f"\n--- SUCCESS ---")
    print(f"Device Name: {device_name}")
    print(f"Device Access Token: {access_token}")

    # Save the token to a file for the logger to use
    token_file = "/home/ubuntu/lt_panel_data_logger/tb_token.txt"
    with open(token_file, "w") as f:
        f.write(access_token)
    print(f"Saved token to {token_file}")

if __name__ == "__main__":
    setup()
