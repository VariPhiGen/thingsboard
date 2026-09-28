import requests
import time
import json
import os

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except ImportError:
    ModbusSerialClient = None
    ModbusTcpClient = None

BASE_URL = os.getenv("TB_BASE_URL", "http://localhost:9091")

def get_ro_token():
    token_file = os.path.join(os.path.dirname(__file__), "ro_token.txt")
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return f.read().strip()
    return os.getenv("RO_SYSTEM_TOKEN", "k8OGd8Sp4jogxtBuYJG5")

RO_TOKEN = get_ro_token()

MODBUS_MODE = os.getenv("MODBUS_MODE", "SERIAL") # "SERIAL" or "TCP"
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB2")
BAUDRATE = int(os.getenv("BAUDRATE", 9600))
MODBUS_TCP_HOST = os.getenv("MODBUS_TCP_HOST", "192.168.1.103")
MODBUS_TCP_PORT = int(os.getenv("MODBUS_TCP_PORT", 502))
SLAVE_ID = int(os.getenv("RO_SLAVE_ID", 1))

def get_modbus_client():
    if not ModbusSerialClient and not ModbusTcpClient:
        return None

    if MODBUS_MODE.upper() == "TCP":
        return ModbusTcpClient(host=MODBUS_TCP_HOST, port=MODBUS_TCP_PORT)
    else:
        return ModbusSerialClient(port=SERIAL_PORT, baudrate=BAUDRATE, parity='N', stopbits=1, bytesize=8, timeout=2)

def read_ro_controller_modbus(client, slave_id):
    """
    Read live RO Plant System parameters (TDS level, Water Flow Rate, RO System Pressure, Operating Status)
    from RO Controller / PLC over Modbus RS485 / TCP.
    """
    if not client:
        return None

    try:
        rr = client.read_holding_registers(0, 4, slave=slave_id)
        if rr.isError():
            rr = client.read_input_registers(0, 4, slave=slave_id)

        if not rr.isError() and len(rr.registers) >= 4:
            tds = round(rr.registers[0] / 10.0, 1)
            water_flow = round(rr.registers[1] / 10.0, 1)
            pressure = round(rr.registers[2] / 10.0, 1)
            status_code = rr.registers[3]

            status_map = {0: "STOPPED", 1: "FILTERING", 2: "BACKWASH", 3: "FLUSHING"}
            status_str = status_map.get(status_code, "RUNNING" if water_flow > 0.5 else "STOPPED")

            return {
                "tds": tds,
                "water_flow": water_flow,
                "pressure": pressure,
                "status": status_str
            }
    except Exception as e:
        print(f"Modbus error for RO Controller Slave ID {slave_id}: {e}")

    return None

def main():
    print("=======================================================")
    print("      RO PLANT SYSTEM MODBUS HARDWARE COLLECTOR        ")
    print("=======================================================")

    client = get_modbus_client()
    if client:
        client.connect()

    url = f"{BASE_URL}/api/v1/{RO_TOKEN}/telemetry"

    try:
        while True:
            telemetry = read_ro_controller_modbus(client, SLAVE_ID)
            if telemetry:
                try:
                    res = requests.post(url, json=telemetry, timeout=5)
                    if res.ok:
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Live RO Hardware Telemetry sent: {telemetry}")
                except Exception as e:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error sending RO telemetry: {e}")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] RO Plant Hardware offline (No Modbus response on port/TCP).")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\nRO collector stopped.")
        if client:
            client.close()

if __name__ == "__main__":
    main()
