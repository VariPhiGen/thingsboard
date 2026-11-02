# Equipment period reports & maintenance log

Downloadable **Daily / Weekly / Monthly / Custom (≤ 31 days)** equipment reports as **PDF** and **Excel**,
plus a **Maintenance Log**, on the ThingsBoard dashboard **Reports & Maintenance**.

Reports cover equipment readings (DG, LT panels, RO, fire suppression), runtime and energy, fuel use and
refuels, alarms, maintenance history (logged work + automatic events) and the predictive-maintenance outlook.

## How it works

```
ThingsBoard ──(nightly)──> daily rollup JSON ──┐
   (raw telemetry, alarms)  reports_data/rollups/YYYY-MM-DD.json
                                               ├─> period model ─> PDF (pdf-generator) / Excel (openpyxl)
ThingsBoard (live) ── maintenance records, ────┘
                      PM outlook
```

- **Rollups** (`rollup.py`): one JSON per IST day built with `infra_reports.collect` (same numbers as the
  daily email PDFs) plus alarm lists, DG fuel use/refuels, maintenance records, PM health, LT feeder energy
  and fire-channel stability. A month of raw telemetry is never fetched at report time. A day missing from
  the store is built on demand when a report needs it; today is always built live (not stored).
- **Maintenance records** are read live at report time (work can be logged after the day).
- **Fuel**: filtered level from the DG Fuel rule node (`fuel_level_pct`) when present, else the raw level
  median-smoothed; refuels from `fuel_event`, or detected from the level on older days. Periods starting or
  ending at the sender's full scale (100 %) are lower bounds ("≥").

## Download API

`GET https://n8n.variphi.com/reports-api/v1/period-reports/download?start=YYYY-MM-DD&end=YYYY-MM-DD&equipment=all|dg,lt,ro,fire&format=pdf|xlsx`

- Header `X-Authorization: Bearer <ThingsBoard JWT>`; accepted only when ThingsBoard confirms the token and
  the user is TENANT_ADMIN/CUSTOMER_USER of the report tenant. CORS allows `https://viot.virtuosonetsoft.com`.
- Served by the `n8n-report-api` container (router included from `vgi-cron-email-script/n8n_report_api.py`);
  nginx (`/etc/nginx/sites-available/n8n.variphi.com`) exposes only `/reports-api/v1/period-reports/`.

## Maintenance log

Widget *Maintenance Log* writes telemetry `maintenance_record` (JSON: type, description, technician,
run_hours, parts, cost, next_due, service_reset, logged_by) on the equipment at the time of the work.
A DG *Preventive service* with "restart the service-due counter" sets `pm_config.last_service_run_hours`,
so the Predictive Maintenance service countdown restarts.

## Maintenance Management (CMMS)

Widget *Maintenance Management* (top of this dashboard): work orders with lifecycle and verification, preventive
maintenance plans (time / run-hours), technical documents with revision and expiry, KPIs, printable job cards.
Server side scheduler, alerts and the full design: see `cmms/README.md`. Completed work orders also write
`maintenance_record`, so they appear in the Maintenance Log and in the period reports.

## Operations

```bash
# nightly rollup of yesterday (schedule at 00:45 IST = 19:15 UTC)
docker exec -w /home/ubuntu/thingsboard n8n-report-api python -m period_reports.rollup --date yesterday --alert
# backfill the last N days that are not stored yet
docker exec -w /home/ubuntu/thingsboard n8n-report-api python -m period_reports.rollup --backfill 120
# widgets + dashboard (idempotent)
python3 -m period_reports.deploy_dashboard
# tests
python3 -m unittest discover -s period_reports/tests -t .
```

Rollups are versioned (`ROLLUP_VERSION`); stored files of an older version are rebuilt when needed.
