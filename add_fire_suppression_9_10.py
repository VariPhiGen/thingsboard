import requests
import json
import copy

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def main():
    print("Logging into ThingsBoard...")
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}
    
    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    dash_id = '51158130-ca34-11f1-a8a7-c1f9998e0221'
    print(f"Fetching dashboard {dash_id}...")
    dashboard = requests.get(f"{BASE_URL}/api/dashboard/{dash_id}", headers=tenant_headers).json()
    print("Dashboard title:", dashboard.get('title'))
    
    # Save a clean backup before making changes
    with open('/home/ubuntu/thingsboard/dashboard_ups_room2_backup.json', 'w') as f:
        json.dump(dashboard, f, indent=2)
    print("Backup saved to /home/ubuntu/thingsboard/dashboard_ups_room2_backup.json")
    
    config = dashboard.get('configuration', {})
    widgets = config.get('widgets', {})
    main_layout = config.get('states', {}).get('default', {}).get('layouts', {}).get('main', {}).get('widgets', {})

    print(f"Current widgets count: {len(widgets)}")
    for w in sorted(widgets.keys()):
        print(f"  {w}: row={widgets[w].get('row')}, col={widgets[w].get('col')}")

    template_widget = widgets['w_pressure_8']

    for i in [9, 10]:
        w_id = f"w_pressure_{i}"
        row = (i - 1) * 4  # row 32 for 9, row 36 for 10
        
        new_widget = copy.deepcopy(template_widget)
        new_widget['id'] = w_id
        new_widget['row'] = row
        new_widget['col'] = 0
        new_widget['sizeX'] = 24
        new_widget['sizeY'] = 4
        
        # Update datasource
        ds = new_widget['config']['datasources'][0]
        ds['dataKeys'][0]['name'] = f"fire_suppression_{i}_pressure"
        ds['dataKeys'][0]['label'] = f"Fire Suppression {i}"
        
        widgets[w_id] = new_widget
        main_layout[w_id] = {
            "sizeX": 24,
            "sizeY": 4,
            "row": row,
            "col": 0
        }
        print(f"Added {w_id} at row {row}")

    print("Pushing updated dashboard to ThingsBoard...")
    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard, headers=tenant_headers)
    if not res.ok:
        print(f"Failed to update dashboard: {res.status_code} {res.text}")
        return False
    print("Dashboard updated successfully!")

    # Verify telemetry for device
    dev_id = '7f45c350-ca32-11f1-a8a7-c1f9998e0221'
    creds = requests.get(f"{BASE_URL}/api/device/{dev_id}/credentials", headers=tenant_headers).json()
    token = creds.get('credentialsId')
    print(f"Device token: {token}")

    telemetry_payload = {
        "ts": 1792427081964,
        "values": {
            "fire_suppression_9_pressure": 1,
            "fire_suppression_10_pressure": 1
        }
    }
    tel_res = requests.post(f"{BASE_URL}/api/v1/{token}/telemetry", json=telemetry_payload)
    print(f"Telemetry post status: {tel_res.status_code}")

    # Verify latest telemetry on device
    latest = requests.get(f"{BASE_URL}/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries", headers=tenant_headers).json()
    print("Verified telemetry keys on device:")
    for k in sorted(latest.keys()):
        print(f"  {k}: {latest[k]}")

    return True

if __name__ == '__main__':
    main()
