# LT Panels Gateway & Electrical Distribution SOP

## System Overview
The LT Panels Gateway monitors electrical parameters across the plant's 8 main electrical substations and distribution panels:
1. **Transformer 1, 2, 3:** Main grid / step-down power feeders.
2. **Electrical Room 1:** Primary distribution for building power.
3. **UPS Room 1 & UPS Panel 2:** Critical IT, server, and automation inverter power.
4. **EVM Charger:** Electric vehicle fleet charging infrastructure.
5. **Fire Fighting Wall:** Fire pump station power.

## Standard Electrical Tolerances
- **Phase-to-Phase Voltage:** 400V - 435V AC (nominal 415V).
- **Phase-to-Neutral Voltage:** 230V - 245V AC.
- **Frequency:** 49.8 Hz – 50.2 Hz (50.0 Hz nominal).
- **Power Factor (PF):** > 0.95 (maintained via APFC capacitor bank).

## Operator Checks & Emergency Protocols
1. **Transformer Overload (> 90% rated kVA):**
   - Check load distribution across Transformers 1, 2, and 3.
   - Coordinate with maintenance to shift loads or curtail EVM charging during peak grid hours.
2. **Voltage Fluctuation or Under-Voltage (< 380V):**
   - Verify OLTC (On-Load Tap Changer) position on incoming transformers.
   - Prepare standby DG Set (DG SET1 / 2 / 3) for synchronization if grid supply is unstable.
3. **High Neutral Current / Voltage Unbalance (> 3%):**
   - Inspect single-phase non-linear loads across Electrical Room 1.
