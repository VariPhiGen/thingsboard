# Ownership guard

Customer users read only the devices of their own customer. Devices of the dashboards kept being moved to the **Public**
customer (silently: no audit entry, ThingsBoard version +1), and then every dashboard shared with the real customer showed
"No data" (`403` on the device telemetry). The cause of that write has not been found (the database has one client only,
ThingsBoard itself; no rule chain, script or app of this host does it). The guard repairs it within about a minute.

Every `GUARD_INTERVAL_S` (60) seconds it reads, from ThingsBoard only:
- the dashboards: the devices of their entity aliases (single entity, entity list) and the customers they are shared with
  (the Public customer is ignored);
- the owner of those devices.

A device owned by Public is given back to the customer its dashboards are shared with: the one that owned it when the
guard last saw it right (state file `~/.local/state/ownership_guard/state.json`), or the only customer shared with. If
that is ambiguous it only logs a warning. A device owned by some other customer is reported, never moved. Aliases that
name devices by a rule (type, name filter) are skipped and logged once. Nothing is hardcoded.

```bash
python3 -m unittest ownership_guard.tests.test_guard
GUARD_DRY_RUN=1 python3 -m ownership_guard.guard --once          # show what it would do
sudo cp ownership_guard/systemd/ownership-guard.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now ownership-guard
journalctl -u ownership-guard -f                                  # "FIXED: <device> was ... assigned back to ..."
```
Each `FIXED` line is a revert that happened: when they show up, note the time: that is the moment to look for the cause.
Credentials come from `.env` like the other services (`TB_TENANT_USER` / `TB_TENANT_PASS`, else sysadmin impersonation).
