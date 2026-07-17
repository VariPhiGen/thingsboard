# Delhivery daily alarm + telemetry report (ThingsBoard CE + n8n)

Branch: `report`

CE has no built-in Reporting module (PE-only). This pipeline generates **CSV + PDF** daily and emails them via n8n.

## Architecture

```
Schedule (08:00 IST)
    → Report API (:5060) fetches ThingsBoard Delhivery alarms + telemetry
    → Writes alarms.csv, telemetry_latest.csv, report.pdf
    → n8n downloads files and emails via SMTP
```

## Components

| Path | Role |
|------|------|
| `scripts/reporting/delhivery_daily_report.py` | Report generator (CSV + PDF) |
| `scripts/reporting/report_server.py` | HTTP API for n8n |
| `scripts/reporting/start_report_api.sh` | Start/restart API on port **5060** |
| `n8n/delhivery-daily-report-workflow.json` | n8n workflow (import) |

Reports are stored under `/var/tmp/delhivery-reports/YYYY-MM-DD/`.

## Quick start

```bash
# 1) Start report API
./scripts/reporting/start_report_api.sh

# 2) Manual generate
curl -X POST http://127.0.0.1:5060/v1/delhivery/daily-report \
  -H 'Content-Type: application/json' \
  -d '{"hours":24}'

# 3) Import n8n workflow (from host)
docker cp n8n/delhivery-daily-report-workflow.json n8n-app:/tmp/delhivery-daily-report-workflow.json
docker exec n8n-app n8n import:workflow \
  --input=/tmp/delhivery-daily-report-workflow.json \
  --userId=4cb6517f-3755-4f94-b9f0-67596be16778
```

Then in n8n UI (`https://n8n.variphi.com`):

1. Open **Delhivery Daily TB Alarm+Telemetry Report**
2. Confirm SMTP credential is attached
3. Adjust `toEmail` if needed
4. **Activate** the workflow
5. Use **Manual test run** once to verify

## Schedule

- Cron: `30 2 * * *` (n8n `GENERIC_TIMEZONE=UTC`)
- Equals **08:00 Asia/Kolkata** every day

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `TB_URL` | `http://127.0.0.1:9091` | Virtuoso ThingsBoard |
| `TB_DELHIVERY_USER_ID` | Delhivery tenant admin UUID | Impersonation target |
| `REPORT_API_PORT` | `5060` | API listen port |
| `REPORT_PUBLIC_BASE` | `http://172.31.16.106:5060` | URL n8n uses to download files |
| `REPORT_OUTPUT_DIR` | `/var/tmp/delhivery-reports` | Output root |
| `REPORT_TZ` | `Asia/Kolkata` | Report timestamps |

## Outputs

- `alarms.csv` — alarms in the lookback window
- `telemetry_latest.csv` — latest telemetry snapshot for monitored devices
- `report.pdf` — printable summary
- `summary.json` — machine-readable totals
