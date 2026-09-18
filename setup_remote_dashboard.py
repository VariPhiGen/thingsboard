import requests
import json
import time

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def setup_all():
    print("Logging into local ThingsBoard API...")
    sys_token = requests.post(f"{BASE_URL}/api/auth/login", json={"username": SYSADMIN_USER, "password": SYSADMIN_PASS}).json()['token']
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    tenants = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data']
    tenant_id = tenants[0]['id']['id']
    
    users = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data']
    admin_user_id = users[0]['id']['id']
    
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json", "Accept": "application/json"}
    
    # 1. Create a Device specifically for this script
    print("Creating Device 'Live Python RO Device'...")
    profiles = requests.get(f"{BASE_URL}/api/deviceProfiles?pageSize=100&page=0", headers=tenant_headers).json()['data']
    profile_id = next((p['id'] for p in profiles if p['name'] == 'default'), profiles[0]['id'])
    
    device_payload = {
        "name": "Live Python RO Device",
        "type": "RO Device",
        "deviceProfileId": profile_id
    }
    # Create or fetch device
    try:
        res = requests.post(f"{BASE_URL}/api/device", json=device_payload, headers=tenant_headers)
        if res.ok:
            device_id = res.json()['id']['id']
        else:
            # Maybe it already exists, let's search for it
            devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=Live Python RO Device", headers=tenant_headers).json()
            device_id = devices['id']['id']
    except Exception as e:
        devices = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=Live Python RO Device", headers=tenant_headers).json()
        device_id = devices['id']['id']

    print(f"Getting Device Token for {device_id}...")
    res = requests.get(f"{BASE_URL}/api/device/{device_id}/credentials", headers=tenant_headers)
    access_token = res.json()['credentialsId']
    
    print("Pushing updated Dashboard with TDS, Temp, and Conductivity...")
    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if d['name'] == 'RO Live Data Dashboard'), None)
    
    with open('/home/ubuntu/thingsboard/remote_ro_dashboard.json', 'r') as f:
        dashboard_config = json.load(f)
        
    # Bind the entity alias to the newly created device ID!
    aliases = dashboard_config.get("configuration", {}).get("entityAliases", {})
    if "ro-device-alias-uuid" in aliases:
        aliases["ro-device-alias-uuid"]["filter"]["singleEntity"]["id"] = device_id
        
    dashboard_payload = {
        "title": dashboard_config.get("title", "RO Live Data Dashboard"),
        "configuration": dashboard_config.get("configuration", {})
    }
    
    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]
        
    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("Dashboard created/updated successfully!")
    else:
        print(f"Failed to push dashboard: {res.text}")

    # Generate the user's python script with the real ACCESS_TOKEN
    script_content = f"""import json
import random
import time
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost" # Internal networking or viot.virtuosonetsoft.com
MQTT_PORT = 1883 # Docker mapping is 1883 for MQTT

ACCESS_TOKEN = "{access_token}"

MQTT_TOPIC = "v1/devices/me/telemetry"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("====================================")
        print("MQTT CONNECTED")
        print("====================================")
    else:
        print(f"MQTT connection failed: {{rc}}")

def on_disconnect(client, userdata, rc):
    print("MQTT disconnected")

client = mqtt.Client()

client.username_pw_set(
    ACCESS_TOKEN,
    ""
)

client.on_connect = on_connect
client.on_disconnect = on_disconnect

print("Connecting to ThingsBoard...")

try:
    client.connect(
        MQTT_HOST,
        MQTT_PORT,
        60
    )
except Exception as e:
    print("Connection error:")
    print(e)
    exit(1)

client.loop_start()

try:
    while True:
        tds = random.randint(100, 500)
        temperature = round(random.uniform(24, 32), 2)
        conductivity = round(random.uniform(100, 800), 2)

        payload = {{
            "tds": tds,
            "temperature": temperature,
            "conductivity": conductivity
        }}

        message = json.dumps(payload)

        result = client.publish(
            MQTT_TOPIC,
            message,
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(
                f"TDS={{tds}} ppm | "
                f"Temperature={{temperature}} C | "
                f"Conductivity={{conductivity}} | "
                f"SENT"
            )
        else:
            print(f"Publish failed: {{result.rc}}")

        time.sleep(5)

except KeyboardInterrupt:
    print("\\nStopping...")
finally:
    client.loop_stop()
    client.disconnect()
    print("Disconnected")
"""
    with open('/home/ubuntu/thingsboard/run_ro_simulation.py', 'w') as f:
        f.write(script_content)
    
    print("\nSetup complete! The python script is ready at /home/ubuntu/thingsboard/run_ro_simulation.py")

if __name__ == "__main__":
    setup_all()
