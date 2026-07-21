# DG SET1 Operator SOPs

## Startup checks
1. Confirm gateway connectivity and fresh telemetry timestamps.
2. Verify engine RPM, oil pressure, and coolant temperature are valid (not N/A / 32767).
3. Confirm breaker and fuel level before start.

## If DG is OFF unexpectedly
1. Confirm whether shutdown was intentional.
2. Check start circuit, emergency stop, fuel supply, and oil pressure.
3. Review active alarms and AI maintenance recommendation.
4. Do not clear alarms until root cause is understood.

## If predictive scoring is PAUSED
1. Required sensors may be missing/invalid.
2. Continue live monitoring from telemetry widgets.
3. Restore sensor feed; scoring resumes automatically when data is healthy.
