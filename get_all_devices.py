import requests
BASE_URL = 'http://localhost:9091'
def get_all():
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": 'sysadmin@thingsboard.org', "password": 'sysadmin'}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
    
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers).json()['data']
    for d in devices:
        res = requests.get(f"{BASE_URL}/api/device/{d['id']['id']}/credentials", headers=tenant_headers).json()
        add_info = d.get('additionalInfo') or {}
        print(f"Device: {d['name']}, ID: {d['id']['id']}, isGateway: {add_info.get('gateway', False)}, CredsType: {res.get('credentialsType')}, CredsID: {res.get('credentialsId')}")
get_all()
