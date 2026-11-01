"""FastAPI router for downloading period reports from the ThingsBoard dashboard.

Mounted by n8n_report_api.py (vgi-cron-email-script); exposed publicly only through nginx at
https://n8n.variphi.com/reports-api/v1/period-reports/ .

Auth: the dashboard widget sends the signed-in user's ThingsBoard JWT. It is accepted when ThingsBoard
itself confirms it (GET /api/auth/user) and the user belongs to the same tenant as the report account.
"""
import hashlib
import logging
import threading
import time
from urllib.parse import quote

import requests
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

from .period import MAX_DAYS, PeriodError
from .service import generate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/period-reports")

ALLOWED_ORIGINS = {"https://viot.virtuosonetsoft.com"}
ALLOWED_AUTHORITIES = {"TENANT_ADMIN", "CUSTOMER_USER"}
TOKEN_CACHE_S = 120
_cache, _cache_lock = {}, threading.Lock()
_tenant = {}


def _cors(request, response):
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


def _service_tenant(settings):
    """(base_url, tenant id) of the account the reports read data with."""
    if not _tenant:
        client = ThingsBoardClient.connect(settings)
        _tenant["base"] = client.base_url
        _tenant["id"] = client._get("/api/auth/user")["tenantId"]["id"]
    return _tenant["base"], _tenant["id"]


def verify_user(token):
    """User dict for a valid ThingsBoard JWT of this tenant, else raises HTTPException(401/403)."""
    if not token:
        raise HTTPException(401, "Sign in to ThingsBoard to download reports")
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    settings = load_settings()
    base, tenant_id = _service_tenant(settings)
    try:
        res = requests.get(f"{base}/api/auth/user", headers={"X-Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(503, f"ThingsBoard unreachable: {exc.__class__.__name__}")
    if res.status_code != 200:
        raise HTTPException(401, "ThingsBoard session expired - reload the dashboard and try again")
    user = res.json()
    if user.get("tenantId", {}).get("id") != tenant_id or user.get("authority") not in ALLOWED_AUTHORITIES:
        raise HTTPException(403, "This account may not download these reports")
    with _cache_lock:
        _cache[key] = (now + TOKEN_CACHE_S, user)
        for k in [k for k, v in _cache.items() if v[0] <= now]:
            _cache.pop(k, None)
    return user


def _token(authorization, x_authorization):
    for h in (x_authorization, authorization):
        if h and h.lower().startswith("bearer "):
            return h[7:].strip()
    return None


@router.options("/download")
def download_preflight(request: Request):
    resp = Response(status_code=204)
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                             "Access-Control-Allow-Methods": "GET, OPTIONS",
                             "Access-Control-Allow-Headers": "Authorization, X-Authorization",
                             "Access-Control-Max-Age": "600"})
    return resp


@router.get("/download")
async def download(request: Request,
                   start: str = Query(..., description="YYYY-MM-DD (IST)"),
                   end: str = Query(..., description="YYYY-MM-DD (IST), inclusive"),
                   equipment: str = Query("all", description=f"all or comma list of dg,lt,ro,fire"),
                   format: str = Query("pdf", pattern="^(pdf|xlsx)$"),
                   authorization: str = Header(None), x_authorization: str = Header(None)):
    try:
        user = verify_user(_token(authorization, x_authorization))
        who = " ".join(x for x in (user.get("firstName"), user.get("lastName")) if x) or user.get("email")
        data, name, ctype = await run_in_threadpool(generate, start, end, equipment, format, who)
    except HTTPException as exc:
        return _cors(request, JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code))
    except PeriodError as exc:
        return _cors(request, JSONResponse({"ok": False, "error": str(exc)}, status_code=400))
    except Exception as exc:
        log.exception("Period report failed")
        return _cors(request, JSONResponse({"ok": False, "error": f"Report generation failed: {exc}"}, status_code=500))
    resp = Response(content=data, media_type=ctype, headers={
        "Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store"})
    return _cors(request, resp)


@router.get("/info")
def info():
    return {"ok": True, "max_days": MAX_DAYS, "formats": ["pdf", "xlsx"], "equipment": ["all", "dg", "lt", "ro", "fire"]}
