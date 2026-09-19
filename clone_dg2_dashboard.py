import requests
import json
import copy

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def clone_dashboard():
    # Login as sysadmin
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    # Get Tenant and Tenant Admin
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    # Get DG Set 2 Dashboard
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    dg2_dashboard_info = next((d for d in dashboards if "DG Set 2 — Woodward KG1500" in d['title']), None)
    
    if not dg2_dashboard_info:
        print("DG Set 2 Dashboard not found")
        return
        
    print(f"Found DG Set 2 Dashboard: {dg2_dashboard_info['title']} (ID: {dg2_dashboard_info['id']['id']})")
    
    # Get the full dashboard configuration
    res = requests.get(f"{BASE_URL}/api/dashboard/info/{dg2_dashboard_info['id']['id']}", headers=tenant_headers)
    full_dg2_dash = requests.get(f"{BASE_URL}/api/dashboard/{dg2_dashboard_info['id']['id']}", headers=tenant_headers).json()
    
    # Get DG Set 3 device ID
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=DG Set 3", headers=tenant_headers).json()
    if not devices:
        print("DG Set 3 device not found")
        return
    dg3_device_id = devices['id']['id']
    print(f"DG Set 3 Device ID: {dg3_device_id}")
    
    # Create the DG Set 3 Dashboard Payload
    dg3_dash = copy.deepcopy(full_dg2_dash)
    
    # Remove existing ID and create dates so it's treated as a new dashboard
    if "id" in dg3_dash:
        del dg3_dash["id"]
    if "createdTime" in dg3_dash:
        del dg3_dash["createdTime"]
        
    dg3_dash["title"] = "DG Set 3 — Woodward KG1500"
    dg3_dash["name"] = "DG Set 3 — Woodward KG1500"
    
    # Update entity alias to point to DG Set 3 device ID
    aliases = dg3_dash.get("configuration", {}).get("entityAliases", {})
    for alias_id, alias_obj in aliases.items():
        if alias_obj.get("filter", {}).get("type") == "singleEntity":
            # Assuming this is the alias for the main device
            alias_obj["filter"]["singleEntity"]["id"] = dg3_device_id
            alias_obj["alias"] = "DG Set 3"
            
    # Check if a dashboard for DG Set 3 already exists and we need to update it
    existing_dg3_dash = next((d for d in dashboards if "DG Set 3 — Woodward KG1500" in d['title']), None)
    if existing_dg3_dash:
        dg3_dash["id"] = existing_dg3_dash["id"]
        print(f"Updating existing DG Set 3 Dashboard (ID: {existing_dg3_dash['id']['id']})")
    else:
        print("Creating new DG Set 3 Dashboard")
        
    res = requests.post(f"{BASE_URL}/api/dashboard", json=dg3_dash, headers=tenant_headers)
    if res.ok:
        print("Successfully created/updated DG Set 3 Dashboard")
    else:
        print(f"Failed: {res.text}")
        
    # Delete the old temporary dashboard if it exists
    temp_dash = next((d for d in dashboards if d['title'] == 'DG Set 3 Live Dashboard'), None)
    if temp_dash:
        print("Deleting temporary 'DG Set 3 Live Dashboard'")
        requests.delete(f"{BASE_URL}/api/dashboard/{temp_dash['id']['id']}", headers=tenant_headers)

if __name__ == "__main__":
    clone_dashboard()
