import requests
import json
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
    profile_id = next((p['id']['id'] for p in profiles if p['name'] == 'woodward_kg150'), None)
    
    if not profile_id:
        print("Creating woodward_kg150 profile...")
        profile_payload = {
            "name": "woodward_kg150",
            "type": "DEFAULT",
            "transportType": "DEFAULT",
            "provisionType": "DISABLED",
            "profileData": {
                "configuration": {"type": "DEFAULT"},
                "transportConfiguration": {"type": "DEFAULT"}
            }
        }
        res = requests.post(f"{BASE_URL}/api/deviceProfile", json=profile_payload, headers=tenant_headers)
        res.raise_for_status()
        profile_id = res.json()['id']['id']
    else:
        print(f"Using existing woodward_kg150 profile ID: {profile_id}")

    print("Creating DG Set 3 Device...")
    device_payload = {
        "name": "DG Set 3",
        "type": "default",
        "deviceProfileId": {"id": profile_id, "entityType": "DEVICE_PROFILE"}
    }
    res = requests.post(f"{BASE_URL}/api/device", json=device_payload, headers=tenant_headers)
    if not res.ok:
        print(f"Failed to create device: {res.text}")
        return
        
    device = res.json()
    device_id = device['id']['id']
    
    print("Getting Device Token...")
    res = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers)
    access_token = res.json()['credentialsId']

    print(f"\n--- SUCCESS ---")
    print(f"Device Name: DG Set 3")
    print(f"Device Access Token: {access_token}")

    print("\nSending initial telemetry...")
    telemetry = {
        "alarm_class_a": 0,
        "alarm_class_b": 0,
        "alarm_class_c": 0,
        "alarm_class_d": 0,
        "alarm_class_e": 0,
        "alarm_class_f": 0,
        "ambient_temp": 31.2
    }
    res = requests.post(f"{BASE_URL}/api/v1/{access_token}/telemetry", json=telemetry)
    print(f"Telemetry sent: {res.status_code}")

if __name__ == "__main__":
    setup()
