import requests

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def check_status():
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=DG Set 2", headers=tenant_headers).json()
    if not devices:
        print("DG Set 2 not found!")
        return
        
    device_id = devices['id']['id']
    print(f"DG Set 2 Device ID: {device_id}")
    
    # Check server-side attributes for "active" status
    attrs = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/attributes/SERVER_SCOPE", headers=tenant_headers).json()
    print("Server Attributes:")
    for attr in attrs:
        print(f" - {attr['key']}: {attr['value']} (Last updated: {attr['lastUpdateTs']})")
        
    # Check latest telemetry timestamp
    keys = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries", headers=tenant_headers).json()
    if keys:
        keys_str = ",".join(keys)
        telemetry = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries?keys={keys_str}", headers=tenant_headers).json()
        print("\nLatest Telemetry:")
        for key, values in telemetry.items():
            if values:
                print(f" - {key}: {values[0]['value']} (Timestamp: {values[0]['ts']})")
    else:
        print("\nNo telemetry keys found.")

if __name__ == "__main__":
    check_status()
