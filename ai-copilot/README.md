# ThingsBoard AI Copilot

Operator-facing multi-device chatbot for ThingsBoard CE (Virtuoso / Delhivery).

The dashboard **Operator Copilot** widget talks to this FastAPI service. Answers are grounded on live readings, alarms, AI scores, history analytics, SOPs (RAG), and daily reports — using the **logged-in user’s JWT** (no admin impersonation for tenant data).

---

## Architecture

```text
TB Dashboard HTML widget
        │  JWT (X-Authorization)
        ▼
  /copilot  (nginx)  ──►  FastAPI :8097
        │
        ├─ Auth          validate JWT via TB /api/auth/user
        ├─ Device resolve  ID / name / alias / clarify
        ├─ Intent          status, alarms, AI, SOP, analytics…
        ├─ Tools           telemetry, alarms, history, compare
        ├─ RAG             knowledge/ SOPs + manuals
        └─ LLM             OpenAI (operator-friendly language)
```

| Layer | Role |
|-------|------|
| Dashboard widget | Conversational UI (light theme). Asks which device first; no device dropdown. |
| Nginx `/copilot/` | Same-origin proxy → `127.0.0.1:8097` |
| FastAPI copilot | Orchestration, tools, RAG, LLM |
| ThingsBoard APIs | Called with the **user JWT** |

Legacy Java endpoint `POST /api/chatbot/operator` is **deprecated** for new dashboards.

---

## Features

### Conversational device selection
1. Copilot asks which device and lists accessible devices.
2. Operator replies with a number (`1`) or name (`DG SET1`).
3. Later questions are scoped to that device.
4. Say **change device** to switch.

### Operator intents
| Intent | Example questions |
|--------|-------------------|
| Status | Is DG SET1 running? Oil / coolant / power? |
| Alarms | What alarms are active? |
| AI guidance | Health score, RUL, recommendations |
| Manual / SOP | How do I check the oil filter? |
| Time-based | Last 2 hours RPM |
| Date-based | Power yesterday / today / on 2026-07-20 |
| Shift-based | Morning / afternoon / night (A/B/C) shift — IST |
| Duration | How long did the DG run today? |
| Statistics | Average / min / max power |
| Trend | Is coolant rising? |
| Comparison | Today vs yesterday power |
| Fleet compare | Compare DG SET1 vs gateway |
| Secrets / config | Blocked (API keys, credentials, config changes) |

### Operator language
Answers avoid product jargon (ThingsBoard, API, telemetry…). Prefer dashboard / live readings / sensors. Markdown bold in replies is rendered in the widget (no raw `*`).

### Plant shifts (IST)
| Shift | Hours (IST) |
|-------|-------------|
| Morning / A | 06:00 – 14:00 |
| Afternoon / B | 14:00 – 22:00 |
| Night / C | 22:00 – 06:00 (next day) |

---

## API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/healthz` | none | Health check |
| `GET` | `/v1/devices` | TB JWT | List devices the user can access |
| `POST` | `/v1/chat` | TB JWT | Operator chat |

**Headers:** `X-Authorization: Bearer <jwt>` or `Authorization: Bearer <jwt>`

### Chat request (JSON)

```json
{
  "message": "Last day status?",
  "conversationId": null,
  "deviceId": null,
  "deviceQuery": null,
  "messages": []
}
```

If `deviceId` is omitted and the message does not name a device, the service returns a clarification list.

### Public URL (production)

```text
https://viot.virtuosonetsoft.com/copilot/  →  http://127.0.0.1:8097/
```

Widgets use same-origin:

```js
window.location.origin + '/copilot'
```

Do **not** point the widget at raw `:8097` / `:8095` ports from the browser.

---

## Project layout

```text
ai-copilot/
├── app/
│   ├── api/chat.py              # /v1/devices, /v1/chat
│   ├── auth/jwt_tb.py           # TB JWT validation
│   ├── models/schemas.py
│   ├── services/
│   │   ├── session.py           # Orchestrator
│   │   ├── device_resolver.py
│   │   ├── intent.py
│   │   ├── time_window.py       # IST windows + shifts
│   │   ├── memory.py            # Conversation + rate limits
│   │   ├── llm.py / prompt_builder.py
│   │   ├── rag.py
│   │   ├── permissions.py
│   │   ├── tb_client.py
│   │   └── tools/               # telemetry, analytics, reports
│   ├── config.py
│   └── main.py
├── knowledge/                   # RAG seed docs + SOPs
├── scripts/ingest_rag.py
├── tests/test_core.py
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

Dashboard widget sources (HTML Container):

- `scripts/dg_set1_dashboard.json` — DG SET1 Operator Copilot panel  
- `scripts/fleet_operator_copilot_dashboard.json` — fleet dashboard  

---

## Run locally

```bash
cd thingsboard/ai-copilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set OPENAI_API_KEY and TB_BASE_URL
python scripts/ingest_rag.py
uvicorn app.main:app --host 0.0.0.0 --port 8097
```

Health check:

```bash
curl -s http://127.0.0.1:8097/healthz
```

### Environment (`.env`)

| Variable | Default | Notes |
|----------|---------|--------|
| `TB_BASE_URL` | `http://127.0.0.1:9091` | ThingsBoard API base |
| `OPENAI_API_KEY` | _(empty)_ | Required for full answers |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model |
| `CORS_ORIGINS` | `*` | Comma-separated or `*` |
| `RAG_PERSIST_DIR` | `./data/chroma` | Chroma persistence |
| `KNOWLEDGE_DIR` | `./knowledge` | SOP / manual docs |
| `REPORTS_DIR` | `/var/tmp/delhivery-reports` | Daily report summaries |
| `LOG_LEVEL` | `INFO` | |

Never commit `.env` (see `.gitignore`).

---

## Docker

```bash
cd thingsboard/ai-copilot
cp .env.example .env   # set OPENAI_API_KEY
docker compose up -d --build
curl -s http://127.0.0.1:8097/healthz
```

Container listens on **8097**. Chroma data is stored in the `copilot-chroma` volume.

---

## Nginx proxy (production)

Example location block (already used on `viot.virtuosonetsoft.com`):

```nginx
location /copilot/ {
    proxy_pass http://127.0.0.1:8097/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Authorization $http_x_authorization;
}
```

---

## Knowledge / RAG

Seed docs live under `knowledge/` (SOPs for DG, gateway, shifts, plus predictive/reporting notes).

Rebuild the index after editing docs:

```bash
source .venv/bin/activate
python scripts/ingest_rag.py
```

Startup also ingests `KNOWLEDGE_DIR` into Chroma automatically.

---

## Tests

```bash
cd thingsboard/ai-copilot
source .venv/bin/activate
pytest tests/ -v
```

Smoke coverage in `tests/test_core.py`: telemetry sentinels, intents, time windows, analytics helpers, device resolver.

---

## Dashboards

| Dashboard | Notes |
|-----------|--------|
| **DG SET1 — Woodward KG1500** | Device dashboard with Operator Copilot widget |
| **Fleet Operator Copilot** | Multi-device copilot surface |

Widget behavior:
- Light theme chat UI  
- No device dropdown — conversational picker  
- Renders `**bold**` as bold text  
- Base URL: `window.location.origin + '/copilot'`

Hard-refresh the browser after widget updates (Ctrl/Cmd+Shift+R).

---

## Security notes

- Tenant data is fetched with the **operator JWT**, not a shared admin token.
- Requests for API keys, passwords, tokens, or config/rule-chain changes are rejected.
- Rate limits apply per user (and device when selected).
- Keep `OPENAI_API_KEY` only in `.env` / secrets manager — never in git.

---

## Related docs in-repo

| Path | Topic |
|------|--------|
| `ai-copilot/knowledge/AI_PREDICTIVE_README.md` | DG SET1 AI predictive pipeline |
| `ai-copilot/knowledge/REPORTING_README.md` | Daily alarm/telemetry reporting |
| `scripts/reporting/README.md` | Report scripts / n8n |
