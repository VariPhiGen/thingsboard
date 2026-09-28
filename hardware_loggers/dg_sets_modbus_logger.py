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

# Access Tokens for all 3 DG Sets
DG_TOKENS = {
    "DG SET1": os.getenv("DG_SET1_TOKEN", "c94imEYvcvPumlhQzr55"),
    "DG SET2": os.getenv("DG_SET2_TOKEN", "t9ELBe1FdIG0DEgMqUrY"),
    "DG SET3": os.getenv("DG_SET3_TOKEN", "eE4vg3BSbUxfi2yns3XL")
}

# Modbus Hardware Configuration
MODBUS_MODE = os.getenv("MODBUS_MODE", "SERIAL") # "SERIAL" or "TCP"
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB1")
BAUDRATE = int(os.getenv("BAUDRATE", 9600))
MODBUS_TCP_HOST = os.getenv("MODBUS_TCP_HOST", "192.168.1.102")
MODBUS_TCP_PORT = int(os.getenv("MODBUS_TCP_PORT", 502))

def get_modbus_client():
    if not ModbusSerialClient and not ModbusTcpClient:
        return None

    if MODBUS_MODE.upper() == "TCP":
        return ModbusTcpClient(host=MODBUS_TCP_HOST, port=MODBUS_TCP_PORT)
    else:
        return ModbusSerialClient(port=SERIAL_PORT, baudrate=BAUDRATE, parity='N', stopbits=1, bytesize=8, timeout=2)

def read_dg_controller_modbus(client, slave_id):
    """
    Read actual live DG parameters (Coolant Temp, Oil Pressure, RPM, Fuel, Voltage, Current, Frequency)
    from Woodward / Cummins / DeepSea Controller over Modbus RS485 / TCP.
    """
    if not client:
        return None

    try:
        # Standard Woodward / DeepSea Modbus holding registers starting at 0
        rr = client.read_holding_registers(0, 11, slave=slave_id)
        if rr.isError():
            rr = client.read_input_registers(0, 11, slave=slave_id)

        if not rr.isError() and len(rr.registers) >= 8:
            coolant_temp = round(rr.registers[0] / 10.0, 1)
            oil_pressure = round(rr.registers[1] / 10.0, 1)
            engine_rpm = float(rr.registers[2])
            fuel_level = round(rr.registers[3] / 10.0, 1)
            battery_voltage = round(rr.registers[4] / 10.0, 1)
            voltage = round(rr.registers[5] / 10.0, 1)
            current = round(rr.registers[6] / 10.0, 1)
            frequency = round(rr.registers[7] / 10.0, 1)

            payload = {
                "coolant_temp": coolant_temp,
                "oil_pressure": oil_pressure,
                "engine_rpm": engine_rpm,
                "fuel_level": fuel_level,
                "battery_voltage": battery_voltage,
                "voltage": voltage,
                "current": current,
                "frequency": frequency,
                "status": "RUNNING" if engine_rpm > 100 else "STOPPED"
            }

            if len(rr.registers) >= 11:
                payload["energy_kwh"] = round(float(rr.registers[8]), 1)
                payload["run_hours"] = round(rr.registers[9] / 10.0, 2)
                payload["engine_starts"] = int(rr.registers[10])

            return payload
    except Exception as e:
        print(f"Modbus error for DG Controller Slave ID {slave_id}: {e}")

    return None

def main():
    print("=======================================================")
    print("  ALL 3 DG SETS REAL MODBUS HARDWARE COLLECTOR ACTIVATED ")
    print("=======================================================")

    client = get_modbus_client()
    if client:
        client.connect()

    try:
        slave_id = 1
        while True:
            for dev_name, token in DG_TOKENS.items():
                telemetry = read_dg_controller_modbus(client, slave_id)
                slave_id = 1 if slave_id >= 3 else slave_id + 1

                if telemetry:
                    url = f"{BASE_URL}/api/v1/{token}/telemetry"
                    try:
                        res = requests.post(url, json=telemetry, timeout=5)
                        if res.ok:
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Live Hardware Telemetry sent for {dev_name}: {telemetry}")
                    except Exception as e:
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error for {dev_name}: {e}")
                else:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {dev_name} Hardware offline (No Modbus response).")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\nDG Sets collector stopped.")
        if client:
            client.close()

if __name__ == "__main__":
    main()
