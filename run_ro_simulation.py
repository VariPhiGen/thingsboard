import json
import random
import time
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost" # Internal networking or viot.virtuosonetsoft.com
MQTT_PORT = 1883 # Docker mapping is 1883 for MQTT

ACCESS_TOKEN = "xpXRcDLWYoUSGGjgIOp9"

MQTT_TOPIC = "v1/devices/me/telemetry"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("====================================")
        print("MQTT CONNECTED")
        print("====================================")
    else:
        print(f"MQTT connection failed: {rc}")

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
        chlorophyll = round(random.uniform(20, 50), 1)
        conductivity = round(random.uniform(800, 1000), 1)
        ec = round(conductivity / 1000.0, 2)
        flow_lpm = round(random.uniform(10, 15), 2)
        flow_simulated = True
        flow_total_l = round(random.uniform(100, 200), 1)
        ph = round(random.uniform(7.0, 10.0), 2)
        salinity = round(random.uniform(0.5, 2.0), 2)
        tds = random.randint(100, 500)

        payload = {
            "chlorophyll": chlorophyll,
            "conductivity": conductivity,
            "ec": ec,
            "flow_lpm": flow_lpm,
            "flow_simulated": flow_simulated,
            "flow_total_l": flow_total_l,
            "ph": ph,
            "salinity": salinity,
            "tds": tds
        }

        message = json.dumps(payload)

        result = client.publish(
            MQTT_TOPIC,
            message,
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(
                f"Chlo={chlorophyll} | Cond={conductivity} | EC={ec} | "
                f"FlowLPM={flow_lpm} | FlowTotal={flow_total_l} | "
                f"pH={ph} | Sal={salinity} | TDS={tds} | SENT"
            )
        else:
            print(f"Publish failed: {result.rc}")

        time.sleep(5)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    client.loop_stop()
    client.disconnect()
    print("Disconnected")
