import requests, json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

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
    
    # Get Root Rule Chain
    rule_chains = requests.get(f"{BASE_URL}/api/ruleChains?pageSize=100&page=0", headers=tenant_headers).json()['data']
    root_rc = next(rc for rc in rule_chains if rc.get('root'))
    rc_id = root_rc['id']['id']
    
    metadata = requests.get(f"{BASE_URL}/api/ruleChain/{rc_id}/metadata", headers=tenant_headers).json()
    
    # Check if Device Profile Node exists
    profile_node_idx = next((i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.profile.TbDeviceProfileNode'), None)
    
    if profile_node_idx is None:
        print("Device Profile Node missing. Adding it...")
        new_dp_node = {
            "additionalInfo": {
                "description": "Process Device Profile Alarms",
                "layoutX": 550,
                "layoutY": 150
            },
            "type": "org.thingsboard.rule.engine.profile.TbDeviceProfileNode",
            "name": "Device Profile Node",
            "debugMode": True,
            "configuration": {
                "persistAlarmRulesState": False,
                "fetchAlarmRulesStateOnStart": False
            }
        }
        profile_node_idx = len(metadata['nodes'])
        metadata['nodes'].append(new_dp_node)
        
        switch_idx = next(i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.filter.TbMsgTypeSwitchNode')
        
        metadata['connections'].append({"fromIndex": switch_idx, "toIndex": profile_node_idx, "type": "Post telemetry"})
        metadata['connections'].append({"fromIndex": switch_idx, "toIndex": profile_node_idx, "type": "Post attributes"})
        
        # Connect success to Save Timeseries (idx 0 usually, but let's find it)
        ts_node_idx = next(i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode' and n.get('name') == 'Save Timeseries')
        metadata['connections'].append({"fromIndex": profile_node_idx, "toIndex": ts_node_idx, "type": "Success"})
        
    else:
        print("Device Profile Node already exists.")
        
    # Get Telegram Webhook Node
    telegram_idx = next((i for i, n in enumerate(metadata['nodes']) if n.get('name') == 'Telegram Webhook REST API'), None)
    
    if telegram_idx is not None:
        # Add connections from Device Profile Node to Telegram
        existing_conns = [(c['fromIndex'], c['toIndex'], c['type']) for c in metadata.get('connections', [])]
        
        for event in ["Alarm Created", "Alarm Updated", "Alarm Cleared"]:
            if (profile_node_idx, telegram_idx, event) not in existing_conns:
                metadata['connections'].append({"fromIndex": profile_node_idx, "toIndex": telegram_idx, "type": event})
                print(f"Added {event} connection from Device Profile to Telegram")

    print("Updating Root Rule Chain metadata...")
    res = requests.post(f"{BASE_URL}/api/ruleChain/metadata", json=metadata, headers=tenant_headers)
    res.raise_for_status()
    print("Successfully updated Root Rule Chain!")

except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'response') and e.response:
        print(e.response.text)
