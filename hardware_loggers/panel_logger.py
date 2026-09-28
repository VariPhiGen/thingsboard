import requests
import json
import time
import os

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except ImportError:
    ModbusSerialClient = None
    ModbusTcpClient = None

BASE_URL = os.getenv("TB_BASE_URL", "http://localhost:9091")
TOKEN_FILE = "/home/ubuntu/lt_panel_data_logger/tb_token.txt"

# Modbus Hardware Settings
MODBUS_MODE = os.getenv("MODBUS_MODE", "SERIAL") # "SERIAL" or "TCP"
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUDRATE = int(os.getenv("BAUDRATE", 9600))
MODBUS_TCP_HOST = os.getenv("MODBUS_TCP_HOST", "192.168.1.101")
MODBUS_TCP_PORT = int(os.getenv("MODBUS_TCP_PORT", 502))

PANELS = [
    ("EVM Charger", "EVM_Charger", 1),
    ("Electrical room 1", "Electrical_room_1", 2),
    ("UPS Room 1", "UPS_Room_1", 3),
    ("Transformer 1", "Transformer_1", 4),
    ("Transformer 2", "Transformer_2", 5),
    ("UPS Panel 2", "UPS_Panel_2", 6),
    ("Transformer 3", "Transformer_3", 7),
    ("Fire fighting wall", "Fire_fighting_wall", 8)
]

def read_token():
    try:
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading token: {e}")
        return None

def get_modbus_client():
    if not ModbusSerialClient and not ModbusTcpClient:
        return None

    if MODBUS_MODE.upper() == "TCP":
        return ModbusTcpClient(host=MODBUS_TCP_HOST, port=MODBUS_TCP_PORT)
    else:
        return ModbusSerialClient(port=SERIAL_PORT, baudrate=BAUDRATE, parity='N', stopbits=1, bytesize=8, timeout=2)

def read_panel_modbus_meter(client, slave_id):
    """
    Read actual live V, I, P, F parameters from physical Energy Meter / Multifunction Meter.
    """
    if not client:
        return None

    try:
        # Standard Modbus Energy Meter holding registers (0: Voltage, 2: Current, 4: Power, 6: Frequency)
        rr = client.read_holding_registers(0, 8, slave=slave_id)
        if rr.isError():
            rr = client.read_input_registers(0, 8, slave=slave_id)

        if not rr.isError() and len(rr.registers) >= 8:
            voltage = round(rr.registers[0] / 10.0, 2)
            current = round(rr.registers[2] / 10.0, 2)
            power = round((voltage * current) / 1000.0, 2)
            frequency = round(rr.registers[6] / 10.0, 2)
            return voltage, current, power, frequency
    except Exception as e:
        print(f"Modbus read error for Slave ID {slave_id}: {e}")

    return None

def main():
    token = read_token()
    if not token:
        print("No access token found. Please run setup_lt_panels.py first.")
        return

    print("=====================================================")
    print("  REAL LIVE LT PANELS MODBUS DATA COLLECTOR ACTIVATED ")
    print("=====================================================")

    client = get_modbus_client()
    if client:
        client.connect()

    url = f"{BASE_URL}/api/v1/{token}/telemetry"

    try:
        while True:
            telemetry = {}
            live_readings_count = 0

            for name, prefix, slave_id in PANELS:
                reading = read_panel_modbus_meter(client, slave_id)
                if reading:
                    voltage, current, power, frequency = reading
                    telemetry[f"{prefix}_voltage"] = voltage
                    telemetry[f"{prefix}_current"] = current
                    telemetry[f"{prefix}_power"] = power
                    telemetry[f"{prefix}_frequency"] = frequency
                    live_readings_count += 1

            if live_readings_count > 0:
                try:
                    response = requests.post(url, json=telemetry, timeout=5)
                    if response.ok:
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Live Hardware Telemetry sent for {live_readings_count} panels.")
                except Exception as req_e:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Request error: {req_e}")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] No real Modbus meter data available (Hardware offline).")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\nLogger stopped.")
        if client:
            client.close()

if __name__ == "__main__":
    main()
