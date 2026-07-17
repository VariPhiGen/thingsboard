# DG SET1 AI Summary + Predictive Maintenance

Branch: `ai`

## What was configured (Delhivery tenant on Virtuoso TB)

1. **AI Model** `DG SET1 OpenAI Predictive` (`gpt-4o-mini`) via Settings → AI Models  
   - API key stored only in ThingsBoard (never commit keys)
2. **Root Rule Chain** path:
   - Save Timeseries → Dedup 45s → Only DG Telemetry → **AI Request** → Normalize → Save AI Predictive Telemetry → If Anomaly → Create Alarm (`AI Predictive Alert`)
3. **Dashboard** [DG SET1 — Woodward KG1500](https://viot.virtuosonetsoft.com/dashboards/09c06030-81cc-11f1-a760-b3ba4cbe1b98)
   - Existing **AI Summary** card (`summary`)
   - Predictive widgets: severity, health_score, failure_risk_pct, rul_hours, predicted_coolant_1h, maintenance_recommendation

## Telemetry keys written by AI

| Key | Meaning |
|-----|---------|
| `summary` | Plain-English operator summary |
| `anomaly` | boolean |
| `severity` | OK / WARNING / CRITICAL |
| `health_score` | 0–100 |
| `failure_risk_pct` | 0–100 |
| `rul_hours` | Estimated remaining useful hours |
| `predicted_coolant_1h` | Predicted coolant °C in ~1h |
| `maintenance_recommendation` | Operator action text |

## Security

- Do **not** commit OpenAI keys to git
- Rotate any key that was pasted in chat
- Set/update key in TB UI: **Settings → AI Models**
