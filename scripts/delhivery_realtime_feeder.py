#!/usr/bin/env python3
"""DISABLED demo telemetry feeder — do not use in production.

This script previously injected simulated data for demo dashboards.
Real dashboards now use live device telemetry only.

To run intentionally (testing only):
  ENABLE_DEMO_FEEDER=1 python3 delhivery_realtime_feeder.py
"""
import os
import sys

if os.environ.get("ENABLE_DEMO_FEEDER") != "1":
    print(
        "Demo feeder is disabled. Delhivery dashboards use real device telemetry.\n"
        "Set ENABLE_DEMO_FEEDER=1 to run simulated data (testing only).",
        file=sys.stderr,
    )
    sys.exit(0)

import json
import random
import time
import urllib.error
import urllib.request

BASE = os.environ.get("TB_URL", "http://127.0.0.1:9091")
DEVICES = {
    "woodward_kg1500_1": os.environ.get("TOKEN_WOODWARD", ""),
}


def telem(token, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/{token}/telemetry",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception as e:
        print(f"telemetry error: {e}", flush=True)
        return None


def tick(i):
    spike = (i % 30) >= 24
    ww_coolant = 112 + random.uniform(-1, 3) if spike else 88 + random.uniform(-2, 3)
    ww_rpm = 2350 + random.uniform(0, 80) if spike else 1500 + random.uniform(-30, 40)
    ww_oil = 150 + random.uniform(-10, 10) if spike else 420 + random.uniform(-15, 15)

    telem(DEVICES["woodward_kg1500_1"], {
        "gen_power_w": round((185 if not spike else 220) * 1000 + random.uniform(-5000, 5000), 0),
        "energy_mwh": round(4069.13 + i * 0.001, 2),
        "run_hours": round(25604.9 + i * 0.0001, 1),
        "engine_starts": 142,
        "engine_rpm": round(ww_rpm, 0),
        "coolant_temp": round(ww_coolant, 2),
        "oil_pressure": round(ww_oil, 1),
        "battery_voltage": round(24.2 + random.uniform(-0.3, 0.3), 2),
        "gen_voltage_wye": round(415 + random.uniform(-2, 2), 1),
        "gen_voltage_delta": round(415 + random.uniform(-2, 2), 1),
        "gen_frequency": round(50.0 + random.uniform(-0.1, 0.1), 2),
        "gen_power_factor": round(0.92 + random.uniform(-0.02, 0.02), 2),
        "anomaly": spike,
        "summary": "Anomaly detected: check coolant/RPM." if spike else "All parameters within normal ranges.",
    })
    mode = "SPIKE" if spike else "normal"
    print(f"tick {i} [{mode}] ww_rpm={ww_rpm:.0f} coolant={ww_coolant:.1f}", flush=True)


def main():
    print(f"WARNING: demo feeder enabled -> {BASE}", flush=True)
    i = 0
    while True:
        i += 1
        tick(i)
        time.sleep(5)


if __name__ == "__main__":
    main()
