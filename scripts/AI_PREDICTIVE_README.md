# DG SET1 AI Summary + Predictive Maintenance

Branch: `ai`

## What was configured (Delhivery tenant on Virtuoso TB)

1. **AI Model** `DG SET1 OpenAI Predictive` (`gpt-4o-mini`) via Settings → AI Models  
   - API key stored only in ThingsBoard (never commit keys)
2. **Root Rule Chain** production AI path (see below)
3. **Dashboard** [DG SET1 — Woodward KG1500](https://viot.virtuosonetsoft.com/dashboards/09c06030-81cc-11f1-a760-b3ba4cbe1b98)
   - **AI Summary** (text only — no repeated status/severity)
   - **AI Status** + **AI Severity** + predictive KPIs (each shown once)
   - Maintenance recommendation (short action; does not repeat summary)
   - Sensor widgets map Modbus sentinel `32767` / `>=30000` to **N/A**

## Production AI path (Root Rule Chain)

```
Save Timeseries
  → DG AI Dedup 5m (300s, FIRST)
  → Only DG Telemetry
  → Core Sensors Valid
       True  → Sanitize DG Sensors → DG SET1 AI Predictive → Clamp AI Outputs → Save AI Predictive Telemetry
       False → Sensor Fault Fallback → Save AI Predictive Telemetry
  → If CRITICAL Equipment (severity===CRITICAL && ai_mode===openai)
       True → AI Predictive Alert
```

### Operator display (production UX)

| State | AI Status | Severity | Health / Risk / RUL / Coolant |
|-------|-----------|----------|-------------------------------|
| Sensors invalid | **PAUSED** | **Sensor Fault** | `--` on all score cards |
| Sensors valid + OpenAI | **ACTIVE** | OK / WARNING / CRITICAL | Real numeric scores |

Fallback **never writes `0`** for predictive KPIs (avoids “0% risk = healthy” misread).  
Detail sits in **AI Reason** / **AI Summary** (not inside the KPI value).

### Hardening behavior

| Stage | Purpose |
|-------|---------|
| **Dedup 5m FIRST** | At most one AI evaluation per device per 5 minutes |
| **Core Sensors Valid** | ≥2 valid among RPM (0–2500), coolant (20–130°C), oil (50–800 kPa) |
| **Sanitize** | Strip invalid metrics; sets `metadata.valid_metric_count` |
| **OpenAI** | JSON predictive scoring on cleaned metrics |
| **Clamp** | Bounds scores; sets `ai_status=ACTIVE`, `ai_mode=openai` |
| **Sensor Fault Fallback** | No OpenAI; `ai_status=PAUSED`; operator-safe `--` KPIs; **SYSTEM** maintenance guidance (deterministic, not LLM) |
| **Alarms** | CRITICAL only when OpenAI says CRITICAL (never on pause) |

**Production note:** Skipping OpenAI when core sensors are invalid is the correct pattern. A fixed SYSTEM maintenance message avoids hallucinated equipment advice from bad/zero Modbus data. OpenAI recommendations appear only when `ai_status=ACTIVE`.

## Telemetry keys written by AI

| Key | Meaning |
|-----|---------|
| `ai_status` | `ACTIVE` or `PAUSED` (operator-facing) |
| `ai_reason` | Why paused / running note |
| `summary` | Plain-English operator summary |
| `anomaly` | boolean |
| `severity` | OK / WARNING / CRITICAL / **Sensor Fault** |
| `health_score` | 0–100 when ACTIVE; `--` when PAUSED |
| `failure_risk_pct` | 0–100 when ACTIVE; `--` when PAUSED |
| `rul_hours` | Hours when ACTIVE; `--` when PAUSED |
| `predicted_coolant_1h` | °C when ACTIVE; `--` when PAUSED |
| `maintenance_recommendation` | Operator action text |
| `ai_mode` | Internal: `openai` or `sensor_fault_fallback` (alarms/debug) |

## IDs (Delhivery)

| Entity | Id |
|--------|----|
| Device `DG SET1` | `3877b730-81cb-11f1-a760-b3ba4cbe1b98` |
| Dashboard | `09c06030-81cc-11f1-a760-b3ba4cbe1b98` |
| AI Model | `d78b28f0-810f-11f1-a760-b3ba4cbe1b98` |
| Root Rule Chain | `1d524b90-6a70-11f1-87c3-df6f31aa9de9` |

## Security

- Do **not** commit OpenAI keys to git
- Rotate any key that was pasted in chat
- Set/update key in TB UI: **Settings → AI Models**
- Do not commit `docker/*-sso*.env` or MQTT private keys
