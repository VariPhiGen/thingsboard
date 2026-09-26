import requests, json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'
NEW_URL = 'http://172.24.0.1:5051'

def login(username, password):
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": username, "password": password})
    res.raise_for_status()
    return res.json()['token']

try:
    print("Logging in...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}
    
    rule_chains = requests.get(f"{BASE_URL}/api/ruleChains?pageSize=100&page=0", headers=tenant_headers).json()['data']
    root_rc = next(rc for rc in rule_chains if rc.get('root'))
    rc_id = root_rc['id']['id']
    
    metadata = requests.get(f"{BASE_URL}/api/ruleChain/{rc_id}/metadata", headers=tenant_headers).json()
    
    telegram_node = next((n for n in metadata['nodes'] if n.get('name') == 'Telegram Webhook REST API'), None)
    if telegram_node:
        telegram_node['configuration']['restEndpointUrlPattern'] = NEW_URL
        print(f"Updating URL to {NEW_URL}")
        res = requests.post(f"{BASE_URL}/api/ruleChain/metadata", json=metadata, headers=tenant_headers)
        res.raise_for_status()
        print("Updated successfully!")
    else:
        print("Node not found!")

except Exception as e:
    print(e)
