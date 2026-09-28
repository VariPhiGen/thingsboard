import requests
import time
import json
import os
import sys

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except ImportError:
    ModbusSerialClient = None
    ModbusTcpClient = None

BASE_URL = os.getenv("TB_BASE_URL", "http://localhost:9091")
TOKEN_FILE = "/home/ubuntu/lt_panel_data_logger/fire_panel_token.txt"

# Modbus Hardware Settings
MODBUS_MODE = os.getenv("MODBUS_MODE", "SERIAL") # "SERIAL" or "TCP"
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUDRATE = int(os.getenv("BAUDRATE", 9600))
MODBUS_TCP_HOST = os.getenv("MODBUS_TCP_HOST", "192.168.1.100")
MODBUS_TCP_PORT = int(os.getenv("MODBUS_TCP_PORT", 502))

REG_LOW_PRESSURE = int(os.getenv("REG_LOW_PRESSURE", 0))
REG_HIGH_PRESSURE = int(os.getenv("REG_HIGH_PRESSURE", 2))

def read_token():
    try:
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading token file: {e}")
        return None

def get_modbus_client():
    if not ModbusSerialClient and not ModbusTcpClient:
        return None

    if MODBUS_MODE.upper() == "TCP":
        return ModbusTcpClient(host=MODBUS_TCP_HOST, port=MODBUS_TCP_PORT)
    else:
        return ModbusSerialClient(port=SERIAL_PORT, baudrate=BAUDRATE, parity='N', stopbits=1, bytesize=8, timeout=2)

def read_panel_modbus_sensor(client, slave_id):
    if not client:
        return None

    try:
        rr = client.read_holding_registers(REG_LOW_PRESSURE, 4, slave=slave_id)
        if rr.isError():
            rr = client.read_input_registers(REG_LOW_PRESSURE, 4, slave=slave_id)

        if not rr.isError() and len(rr.registers) >= 4:
            raw_low = rr.registers[0]
            raw_high = rr.registers[2]
            return round(raw_low / 10.0, 2), round(raw_high / 10.0, 2)
    except Exception as e:
        print(f"Modbus error for Slave ID {slave_id}: {e}")

    return None

def main():
    token = read_token()
    if not token:
        print("No master token found. Please run consolidate_fire_panels_single_device.py first.")
        return

    print("==========================================================")
    print("  SINGLE-DEVICE 10-PANEL REAL MODBUS HARDWARE COLLECTOR  ")
    print("==========================================================")

    client = get_modbus_client()
    if client:
        client.connect()

    url = f"{BASE_URL}/api/v1/{token}/telemetry"

    try:
        while True:
            telemetry = {}
            live_panels_count = 0

            for i in range(1, 11):
                slave_id = i
                reading = read_panel_modbus_sensor(client, slave_id)
                if reading:
                    p_low, p_high = reading
                    telemetry[f"fire_panel_{i}_pressure_low"] = p_low
                    telemetry[f"fire_panel_{i}_pressure_high"] = p_high
                    live_panels_count += 1

            if live_panels_count > 0:
                try:
                    response = requests.post(url, json=telemetry, timeout=5)
                    if response.ok:
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Live Hardware Telemetry sent for {live_panels_count} Fire Panels.")
                except Exception as req_e:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Request error: {req_e}")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Hardware offline (No real Modbus readings available).")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\nHardware data collector stopped.")
        if client:
            client.close()

if __name__ == "__main__":
    main()
