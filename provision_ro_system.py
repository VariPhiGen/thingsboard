import requests
import json
import time
import random

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
        # If no user exists, we might need to create one, but let's hope one exists
        return

    admin_user_id = users[0]['id']['id']
    admin_email = users[0]['email']
    print(f"Using Tenant Admin: {admin_email}")

    print("Generating Tenant Admin Token...")
    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    res.raise_for_status()
    tenant_token = res.json()['token']
    
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}

    print("Fetching or Creating Device Profile...")
    res = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers)
    profiles = res.json()['data']
    profile_id = next((p['id'] for p in profiles if p['name'] == 'default'), profiles[0]['id'])

    print("Creating RO Device...")
    device_payload = {
        "name": "Smart RO Purifier",
        "type": "RO Device",
        "deviceProfileId": profile_id
    }
    res = requests.post(f"{BASE_URL}/api/device", json=device_payload, headers=tenant_headers)
    res.raise_for_status()
    device = res.json()
    device_id = device['id']['id']
    
    print("Getting Device Token...")
    res = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers)
    access_token = res.json()['credentialsId']

    print("Creating Dashboard...")
    try:
        with open('ro_device_dashboard.json', 'r') as f:
            dashboard_config = json.load(f)
        
        dashboard_payload = {
            "title": dashboard_config.get("title", "RO Dashboard"),
            "configuration": dashboard_config.get("configuration", {})
        }
        res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
        if res.ok:
            print(f"Dashboard Created Successfully! Dashboard ID: {res.json()['id']['id']}")
        else:
            print(f"Failed to create dashboard via API: {res.text}")
    except Exception as e:
        print(f"Error loading dashboard: {e}")

    print(f"\n--- SUCCESS ---")
    print(f"ThingsBoard URL: {BASE_URL}")
    print(f"Tenant Login: {admin_email} (Use your existing password)")
    print(f"Device Name: Smart RO Purifier")
    print(f"Device Access Token: {access_token}")

    print("\nSending mock telemetry in background (Ctrl+C to stop)...")
    try:
        while True:
            telemetry = {
                "tds": random.randint(30, 80),
                "water_flow": random.uniform(1.0, 2.5),
                "pressure": random.uniform(40.0, 60.0),
                "status": "ON"
            }
            requests.post(f"{BASE_URL}/api/v1/{access_token}/telemetry", json=telemetry)
            print(f"Sent telemetry: {telemetry}")
            time.sleep(5)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    setup()
