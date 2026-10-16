# DG data fixes in ThingsBoard (16 Oct 2026)

These scripts record changes made to the live ThingsBoard instance (`virtuoso-tb`, port 9091) for
the three Woodward KG1500 DG sets. Every change was already applied on 16 Oct 2026, and each script
refuses to apply twice. Backups of what they replaced are in `/home/ubuntu/tb_alarm_fix/backup/`.
Run them from the project root (`python3 scripts/tb_dg_fixes/<script>`). Without `--apply` they
only print what they would do. They log in with the credentials in `.env`.

| Script | Change |
|---|---|
| `deploy_dg_status_debounce.py <backup.json> [--apply]` | Root rule chain: `dg_status` changes only after the new state holds (OFF 120 s, RUNNING 60 s). This stops the 'DG Offline' alarm and Telegram message from flapping when a Modbus read fails or the engine coasts down. |
| `deploy_energy_meter_scale.py <backup.json> [--apply]` | Root rule chain: multiplies `energy_kwh` by the device server attribute `energy_kwh_scale` and keeps the controller value as `energy_kwh_raw`. Devices without the attribute are not changed. |
| `set_energy_scale.py <value>` | Sets `energy_kwh_scale` on every `woodward_kg1500` device. It is now 0.1, because the controller kWh counter arrives 10x too high. **If the gateway multiplier is ever fixed on site, run it with `1`.** |
| `rescale_energy_history.py [--apply]` | One-off: divided the stored `energy_kwh` history by 10. It skips points that already have `energy_kwh_raw`, text values, sensor-offline codes and the 19 Sep 2026 simulator data. |
| `dashboard_sensor_na.py --test-copy / --apply <backupdir> / --delete <id>` | DG dashboards: sensor-offline codes (32767/65535) and `error` reads show as N/A on cards and as gaps in charts, instead of fake numbers. |

The JavaScript run by the rule nodes is in `rule_nodes/`.
