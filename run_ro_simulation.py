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
        tds = random.randint(100, 500)
        temperature = round(random.uniform(24, 32), 2)
        conductivity = round(random.uniform(100, 800), 2)

        payload = {
            "tds": tds,
            "temperature": temperature,
            "conductivity": conductivity
        }

        message = json.dumps(payload)

        result = client.publish(
            MQTT_TOPIC,
            message,
            qos=1
        )

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(
                f"TDS={tds} ppm | "
                f"Temperature={temperature} C | "
                f"Conductivity={conductivity} | "
                f"SENT"
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
