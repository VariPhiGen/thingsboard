import requests
import string
import random
BASE_URL = 'http://localhost:9091'
def change_creds():
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": 'sysadmin@thingsboard.org', "password": 'sysadmin'}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
    
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=gateway001", headers=tenant_headers).json()
    device_id = devices['id']['id']
    
    # Generate new token
    new_token = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
    
    # Delete existing creds and create new ones (or just update)
    creds = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers).json()
    creds['credentialsType'] = 'ACCESS_TOKEN'
    creds['credentialsId'] = new_token
    # X509 uses credentialsValue for cert, ACCESS_TOKEN usually uses credentialsId
    creds['credentialsValue'] = None
    
    res = requests.post(f"{BASE_URL}/api/device/credentials", json=creds, headers=tenant_headers)
    if res.ok:
        print(f"Successfully updated gateway001 to ACCESS_TOKEN: {new_token}")
    else:
        print(f"Failed to update credentials: {res.text}")

change_creds()
