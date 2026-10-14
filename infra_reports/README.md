# Daily infrastructure PDF reports

Four PDFs (DG Sets, LT Panels, Fire Suppression, RO Plant) with 24-hour statistics and time series graphs,
emailed daily at 08:00 IST by the n8n workflow *Infrastructure 4 Separate PDFs Daily Report*
(→ `n8n-report-api` → `generate_separate_pdfs_report.py`).

## Run

```bash
python3 generate_separate_pdfs_report.py --preview                     # last 24 h → report_previews/
python3 generate_separate_pdfs_report.py --preview --date=2026-10-12   # one past IST day
python3 generate_separate_pdfs_report.py --send --to=a@x.com           # email (default: REPORT_RECIPIENTS)
python3 -m unittest discover -s infra_reports/tests -t .               # tests
```

Exit code is non-zero on any failure. `--alert` also sends a Telegram alert (the n8n path always does).

## Configuration (`/home/ubuntu/thingsboard/.env`, process env as fallback)

| Key | Purpose |
|---|---|
| `TB_TENANT_USER`, `TB_TENANT_PASS` | Preferred: dedicated tenant login |
| `TB_SYSADMIN_USER`, `TB_SYSADMIN_PASS`, `TB_TENANT_ID` | Fallback: sysadmin impersonating a tenant admin of `TB_TENANT_ID` |
| `TB_BASE_URL` | ThingsBoard URL(s), tried before the Docker defaults |
| `PDF_SERVICE_URL` | pdf-generator URL(s) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Email delivery (465 = SSL, otherwise STARTTLS) |
| `REPORT_RECIPIENTS` | Comma-separated recipients (required to send) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Failure alerts |
| `REPORT_PROFILES_DG/LT/FIRE/RO` | Override the ThingsBoard device profiles per report |

The process environment is never modified (the package runs inside the shared n8n report API).

## How the numbers are produced

- Devices are selected by **device profile**, not by name (`config.DEFAULT_PROFILES`).
- Raw telemetry for the window is fetched once per device; sensor-offline codes (32767/65535), `error` and
  text values are dropped; booleans become 1/0.
- Graphs: 30-minute bucket averages (gaps stay gaps). Fire signals: share of OK samples per bucket.
- 24h avg/min/max are computed from the raw samples, not ThingsBoard's server-side aggregates
  (those include the 32767 codes).
- **DG 24h Energy** integrates `power_kw` over time (trapezoidal; gaps > 5 min are not counted). The
  controller kWh meter change is shown beside it and flagged when they differ by more than 1.25x.
- A latest value older than the report period is greyed with its date and excluded from live totals.
- Alarms: live report = currently active (`searchStatus=ACTIVE`); `--date` = alarms created that day.

## Failure behaviour

Fail closed: if ThingsBoard, the PDF service or SMTP fails (after retries), no email — and no partial
email — is sent; the n8n run fails with the error and a Telegram alert is sent when configured.
