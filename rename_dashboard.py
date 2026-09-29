import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login():
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS})
    return res.json()['token']

def rename_dashboard():
    sys_token = login()
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
    
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target = next((d for d in dashboards if d['title'] == 'LT Panel Fire Dashboard'), None)
    
    if target:
        target['title'] = 'Fire Suppression'
        target['name'] = 'Fire Suppression'
        res = requests.post(f"{BASE_URL}/api/dashboard", json=target, headers=tenant_headers)
        if res.ok:
            print("Successfully renamed dashboard to 'Fire Suppression'")
        else:
            print(f"Failed to rename: {res.text}")
    else:
        print("Dashboard 'LT Panel Fire Dashboard' not found.")

if __name__ == "__main__":
    rename_dashboard()
