# DG Sets (DG SET1, DG Set 2, DG Set 3) Operator SOPs

## Overview
The plant has 3 industrial Diesel Generator sets powered by Woodward KG1500 controllers:
- **DG SET1:** Main emergency backup generator.
- **DG Set 2:** Auxiliary backup generator.
- **DG Set 3:** Secondary backup generator.

## Startup Checks & Normal Running Parameters
1. **Engine Speed:** ~1500 RPM (50.0 Hz).
2. **Coolant Temperature:** 70°C – 92°C (Alarm at > 98°C, Trip at > 105°C).
3. **Oil Pressure:** 3.5 – 5.5 bar when running (Alarm at < 2.0 bar, Trip at < 1.2 bar). When engine is stopped, 0 bar is normal.
4. **Battery Voltage:** 24.0V – 28.5V DC (Alarm at < 23.5V).
5. **Fuel Level:** Always maintain above 60% for emergency standby.
6. **Active Power:** 0 kW on standby, up to rated kVA on emergency load.

## Troubleshooting
1. **DG Stopped Unexpectedly:**
   - Verify if shutdown was intentional or due to an emergency stop / trip.
   - Check fuel supply, low oil pressure trip, or high coolant temperature trip.
   - Do not restart before investigating root cause.
2. **High Coolant Temp (> 95°C):**
   - Check radiator coolant level, fan belt tension, and radiator fins for blockage.
3. **Battery Low Voltage (< 24V):**
   - Check static battery charger supply and alternator charging circuit.
