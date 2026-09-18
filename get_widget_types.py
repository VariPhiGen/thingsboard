import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def get_widget_types():
    # 1. SysAdmin login
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS})
    sys_token = res.json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    # 2. Get first tenant
    res = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers)
    tenant_id = res.json()['data'][0]['id']['id']
    
    # 3. Get tenant admin
    res = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers)
    admin_user_id = res.json()['data'][0]['id']['id']
    
    # 4. Get tenant admin token
    res = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers)
    tenant_token = res.json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    # 5. Get all widget types
    res = requests.get(f"{BASE_URL}/api/widgetTypes?isSystem=true&pageSize=500&page=0", headers=tenant_headers)
    if not res.ok:
        print(f"Error fetching widget types: {res.text}")
        return
        
    widgets = res.json()['data']
    with open("/tmp/widgets.json", "w") as f:
        json.dump(widgets, f, indent=2)
    print("Widgets dumped to /tmp/widgets.json")

if __name__ == "__main__":
    get_widget_types()
