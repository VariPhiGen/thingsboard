# ThingsBoard AI Copilot (FastAPI)

Production multi-device operator chatbot backend for ThingsBoard CE.

## Architecture

Dashboard widget (JWT) → `POST /v1/chat` → Device Resolver / Intent / Tools / RAG / LLM  
Tools call ThingsBoard APIs **with the user JWT** (no service admin impersonation for tenant data).

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/healthz` | none | Health |
| GET | `/v1/devices` | TB JWT | List accessible devices |
| POST | `/v1/chat` | TB JWT | Operator chat |

Headers accepted: `X-Authorization: Bearer <jwt>` or `Authorization: Bearer <jwt>`.

## Run locally

```bash
cd thingsboard/ai-copilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY and TB_BASE_URL
python scripts/ingest_rag.py
uvicorn app.main:app --host 0.0.0.0 --port 8097
```

## Docker

```bash
cd thingsboard/ai-copilot
cp .env.example .env
# edit OPENAI_API_KEY
docker compose up -d --build
curl -s http://127.0.0.1:8097/healthz
```

Default port: **8097**.

## Widget cutover

The DG SET1 / Fleet Operator Chat widgets call this service (`copilotBaseUrl`, default `http://127.0.0.1:8097` or your public host).  
Legacy Java endpoint `POST /api/chatbot/operator` remains as fallback only and is deprecated for new dashboards.

## Knowledge / RAG

Seed docs live in `knowledge/`. Rebuild index:

```bash
python scripts/ingest_rag.py
```
