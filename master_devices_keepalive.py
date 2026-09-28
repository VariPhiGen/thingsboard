import requests
import time
import os

BASE_URL = os.getenv("TB_BASE_URL", "http://localhost:9091")

# Access Tokens for all 6 Master Devices
MASTER_TOKENS = {
    "DG SET1": os.getenv("DG_SET1_TOKEN", "c94imEYvcvPumlhQzr55"),
    "DG SET2": os.getenv("DG_SET2_TOKEN", "t9ELBe1FdIG0DEgMqUrY"),
    "DG SET3": os.getenv("DG_SET3_TOKEN", "eE4vg3BSbUxfi2yns3XL"),
    "RO Plant System": os.getenv("RO_SYSTEM_TOKEN", "k8OGd8Sp4jogxtBuYJG5"),
    "LT Panel Fire": os.getenv("FIRE_PANEL_TOKEN", "DJ7FST2DirV7zteDUNJM"),
    "LT Panels Gateway": os.getenv("LT_GATEWAY_TOKEN", "53T4hJ7CYVI7qXkh3QJN")
}

def send_keepalive():
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] Sending active heartbeat to all Master Devices...")
    
    for dev_name, token in MASTER_TOKENS.items():
        url = f"{BASE_URL}/api/v1/{token}/telemetry"
        payload = {"ping": 1}
        try:
            res = requests.post(url, json=payload, timeout=5)
            if res.ok:
                print(f"  ✅ {dev_name:<20}: Active Heartbeat OK")
            else:
                print(f"  ❌ {dev_name:<20}: HTTP {res.status_code}")
        except Exception as e:
            print(f"  ⚠️ {dev_name:<20}: {e}")

def main():
    print("=======================================================")
    print("   MASTER DEVICES ALWAYS-ACTIVE WATCHDOG ACTIVATED    ")
    print("=======================================================")
    
    while True:
        send_keepalive()
        time.sleep(180) # Pulse every 3 minutes (180s) to keep all devices ACTIVE in ThingsBoard

if __name__ == "__main__":
    main()
