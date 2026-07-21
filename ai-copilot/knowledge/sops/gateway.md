# Gateway Operator SOP

## Health checks
1. Confirm gateway device is online in ThingsBoard.
2. Check last activity time and connectivity telemetry.
3. Verify downstream DG devices are still publishing.

## If gateway offline
1. Check power and network path.
2. Validate MQTT/HTTP connectivity settings.
3. Confirm certificates/credentials without exposing secrets in chat.
4. After recovery, confirm DG SET1 telemetry resumes.
