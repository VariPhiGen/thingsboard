import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def fix_aliases():
    print("Logging in to ThingsBoard...")
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    # Fetch Real Master Devices
    devices = requests.get(f"{BASE_URL}/api/tenant/devices?pageSize=100&page=0", headers=tenant_headers).json()['data']
    dg1_id = next(d['id']['id'] for d in devices if d['name'] == 'DG SET1')
    dg2_id = next(d['id']['id'] for d in devices if d['name'] == 'DG SET2')
    dg3_id = next(d['id']['id'] for d in devices if d['name'] == 'DG SET3')

    print(f"Master Device IDs:\n DG SET1: {dg1_id}\n DG SET2: {dg2_id}\n DG SET3: {dg3_id}\n")

    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']

    # Update Dashboard for DG SET2
    dash_dg2 = next((d for d in dashboards if 'DG Set 2' in d['title'] or 'DG SET2' in d['title']), None)
    if dash_dg2:
        d_obj = requests.get(f"{BASE_URL}/api/dashboard/{dash_dg2['id']['id']}", headers=tenant_headers).json()
        config = d_obj.get('configuration', {})
        aliases = config.get('entityAliases', {})
        for alias_key, alias_val in aliases.items():
            if alias_val.get('filter', {}).get('type') == 'singleEntity':
                alias_val['filter']['singleEntity']['id'] = dg2_id
                alias_val['alias'] = 'DG SET2'
        
        res_update = requests.post(f"{BASE_URL}/api/dashboard", json=d_obj, headers=tenant_headers)
        print(f"Updated Dashboard 'DG SET2': Status {res_update.status_code}")

    # Update Dashboard for DG SET3
    dash_dg3 = next((d for d in dashboards if 'DG Set 3' in d['title'] or 'DG SET3' in d['title']), None)
    if dash_dg3:
        d_obj = requests.get(f"{BASE_URL}/api/dashboard/{dash_dg3['id']['id']}", headers=tenant_headers).json()
        config = d_obj.get('configuration', {})
        aliases = config.get('entityAliases', {})
        for alias_key, alias_val in aliases.items():
            if alias_val.get('filter', {}).get('type') == 'singleEntity':
                alias_val['filter']['singleEntity']['id'] = dg3_id
                alias_val['alias'] = 'DG SET3'
        
        res_update = requests.post(f"{BASE_URL}/api/dashboard", json=d_obj, headers=tenant_headers)
        print(f"Updated Dashboard 'DG SET3': Status {res_update.status_code}")

if __name__ == "__main__":
    fix_aliases()
