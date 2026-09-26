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
    print("Fetching rule chains...")
    rule_chains = requests.get(f"{BASE_URL}/api/ruleChains?pageSize=100&page=0", headers=tenant_headers).json()['data']
    root_rc = next(rc for rc in rule_chains if rc.get('root'))
    rc_id = root_rc['id']['id']
    
    print(f"Fetching metadata for Root Rule Chain (ID: {rc_id})...")
    metadata = requests.get(f"{BASE_URL}/api/ruleChain/{rc_id}/metadata", headers=tenant_headers).json()
    
    # Check if Telegram node already exists
    if any(n.get('name') == 'Telegram Webhook REST API' for n in metadata['nodes']):
        print("Telegram Webhook node already exists. Exiting.")
        exit(0)
    
    # Find Message Type Switch
    switch_idx = next(i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.filter.TbMsgTypeSwitchNode')
    
    # Find TbDeviceProfileNode if exists
    profile_node_idx = next((i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.profile.TbDeviceProfileNode'), None)
    
    new_node = {
        "additionalInfo": {
            "description": "Send Alarm to Telegram",
            "layoutX": 825,
            "layoutY": 750
        },
        "type": "org.thingsboard.rule.engine.rest.TbRestApiCallNode",
        "name": "Telegram Webhook REST API",
        "debugMode": True,
        "configuration": {
            "restEndpointUrlPattern": "http://localhost:5051",
            "requestMethod": "POST",
            "maxParallelRequestsCount": 0,
            "headers": {"Content-Type": "application/json"},
            "useSimpleClientHttpFactory": False,
            "readTimeoutMs": 0,
            "maxRequestTimeout": 10000,
            "useRedisQueueForMsgPersistence": False,
            "trimQueue": False,
            "maxQueueSize": 0
        }
    }
    
    new_node_idx = len(metadata['nodes'])
    metadata['nodes'].append(new_node)
    
    # Add connections from Message Type Switch
    metadata['connections'].append({"fromIndex": switch_idx, "toIndex": new_node_idx, "type": "Alarm Created"})
    metadata['connections'].append({"fromIndex": switch_idx, "toIndex": new_node_idx, "type": "Alarm Updated"})
    metadata['connections'].append({"fromIndex": switch_idx, "toIndex": new_node_idx, "type": "Alarm Cleared"})
    
    # If device profile node exists, also connect from it
    if profile_node_idx is not None:
        metadata['connections'].append({"fromIndex": profile_node_idx, "toIndex": new_node_idx, "type": "Alarm Created"})
        metadata['connections'].append({"fromIndex": profile_node_idx, "toIndex": new_node_idx, "type": "Alarm Updated"})
        metadata['connections'].append({"fromIndex": profile_node_idx, "toIndex": new_node_idx, "type": "Alarm Cleared"})
    
    # For custom alarms
    create_alarm_nodes = [i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.action.TbCreateAlarmNode']
    for idx in create_alarm_nodes:
        metadata['connections'].append({"fromIndex": idx, "toIndex": new_node_idx, "type": "Created"})
        metadata['connections'].append({"fromIndex": idx, "toIndex": new_node_idx, "type": "Updated"})
        
    clear_alarm_nodes = [i for i, n in enumerate(metadata['nodes']) if n.get('type') == 'org.thingsboard.rule.engine.action.TbClearAlarmNode']
    for idx in clear_alarm_nodes:
        metadata['connections'].append({"fromIndex": idx, "toIndex": new_node_idx, "type": "Cleared"})
    
    print("Updating Root Rule Chain metadata...")
    res = requests.post(f"{BASE_URL}/api/ruleChain/metadata", json=metadata, headers=tenant_headers)
    res.raise_for_status()
    print("Successfully updated Root Rule Chain!")

except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'response') and e.response:
        print(e.response.text)
