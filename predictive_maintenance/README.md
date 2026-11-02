# Predictive maintenance (ThingsBoard rule chain "Predictive Maintenance")

`pm_compute.js` (node *PM Compute*, every 5 min per device) and `dg_fuel.js` (node *DG Fuel*) contain **no thresholds**.
Each device carries its configuration in the server attribute `pm_config`:

| Field | Content |
|---|---|
| `kind` | DG, LT, RO or FIRE - decides the checks; the rule chain routes by it (node *Fetch PM Config* runs first) |
| `engine` | scoring penalties, health bands, hysteresis, staleness, controller "not available" codes, trend parameters, time zone |
| `limits` | telemetry keys, valid ranges and every threshold of the checks (battery, fuel, coolant, oil, frequency, voltage, load, service, exercise, starts, LT feeders, RO TDS/temperature/pH/pressure, fire channels) |

A limit that is not configured switches only its check off and is reported as INFO "Some checks are not configured";
without `engine`/`limits` the device reports `pm_status = NOT CONFIGURED`. Values are edited on the dashboard
(Reports & Maintenance > Maintenance Management > Settings > Predictive maintenance) and apply from the next evaluation.

`pm_seed.json` is the template. `migrate_config.py` wrote it into the devices once (keeping values a device already had)
and derived per-device values from each device's own history with the template's `derive` rules: 12 V / 24 V battery
system, nominal voltage of the DG output and of each LT feeder, RO TDS warning level. It also stores the template on the
asset *Maintenance Settings* (`pm_templates`) so new equipment can be configured from the dashboard.

```bash
python3 -m predictive_maintenance.migrate_config --dry-run
python3 -m predictive_maintenance.migrate_config --apply --backup-dir predictive_maintenance/backups
node predictive_maintenance/test_pm_compute.js && node predictive_maintenance/test_dg_fuel.js
```
