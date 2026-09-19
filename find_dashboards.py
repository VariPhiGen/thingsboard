import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def find():
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    for d in dashboards:
        print(f"ID: {d['id']['id']}, Name: {d['title']}")

if __name__ == "__main__":
    find()
