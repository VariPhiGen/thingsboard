"""HTTP API of the Maintenance Management dashboard (mounted by report_api_server.py under /cmms/v1).

Public URL: https://viot.virtuosonetsoft.com/report-api/cmms/v1/... (nginx -> 127.0.0.1:5055), same origin as the
dashboard, so no CORS is allowed or needed.

Every request carries the signed-in ThingsBoard user's JWT (header X-Authorization: Bearer <token>). The token is
accepted only when ThingsBoard itself confirms it (GET /api/auth/user) and the user belongs to the tenant of the
service account; the user's maintenance role then decides what is allowed (cmms/roles.py). Changes are made with the
service account (thingsboard/.env), so customer users need no write access to the maintenance records.

  GET  /cmms/v1/state                     everything the dashboard shows for this user
  GET  /cmms/v1/users                     users and their roles (admin)
  GET  /cmms/v1/profiles                  device profile names (admin)
  GET  /cmms/v1/files/<id>                download a document / attachment the user may see
  POST /cmms/v1/upload?purpose=attachment|document&name=<file name>   raw file body -> {id, ...}
  POST /cmms/v1/action/<name>             JSON command (see Service.do_<name>)
"""
import hashlib
import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, quote, urlparse

from . import roles as R
from .model import TransitionError
from .service import ConflictError, Invalid, NotFound, Service, Uploads, User, user_name
from .store import Store, StoreError

log = logging.getLogger("cmms.api")

PREFIX = "/cmms/v1"
TOKEN_CACHE_S = 60            # a revoked / signed-out token stops working within this time
CLIENT_MAX_AGE_S = 1800       # service-account session is renewed well before the ThingsBoard token expires
UPLOAD_MAX_AGE_S = 86400      # files uploaded but never attached are deleted after a day
MAX_JSON = 2 * 1048576
ALLOWED_AUTHORITIES = {"TENANT_ADMIN", "CUSTOMER_USER"}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, connect):
        """connect(): a logged-in ThingsBoardClient of the service (tenant) account."""
        self._connect = connect
        self._client, self._client_ts, self._tenant = None, 0, None
        self._lock = threading.Lock()
        self._tokens = {}
        self.uploads = Uploads(UPLOAD_MAX_AGE_S)

    # ------------------------------------------------------------------ service account
    def client(self, fresh=False):
        with self._lock:
            if fresh or self._client is None or time.time() - self._client_ts > CLIENT_MAX_AGE_S:
                self._client = self._connect()
                self._client_ts = time.time()
                me = self._client.session.request("GET", f"{self._client.base_url}/api/auth/user",
                                                  headers=self._client._headers, timeout=30).json()
                self._tenant = me["tenantId"]["id"]
            return self._client

    # ------------------------------------------------------------------ authentication
    def authenticate(self, headers):
        auth = headers.get("X-Authorization") or headers.get("Authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            raise HttpError(401, "Sign in to ThingsBoard")
        key, now = hashlib.sha256(token.encode()).hexdigest(), time.time()
        with self._lock:
            hit = self._tokens.get(key)
            if hit and hit[0] > now:
                return hit[1]
        c = self.client()
        try:
            res = c.session.request("GET", f"{c.base_url}/api/auth/user", headers={"X-Authorization": f"Bearer {token}"}, timeout=15)
        except Exception as exc:
            raise HttpError(503, f"ThingsBoard unreachable: {exc.__class__.__name__}")
        if res.status_code != 200:
            raise HttpError(401, "ThingsBoard session expired - reload the dashboard")
        u = res.json()
        if (u.get("tenantId") or {}).get("id") != self._tenant or u.get("authority") not in ALLOWED_AUTHORITIES:
            raise HttpError(403, "This account has no access to maintenance management")
        with self._lock:
            self._tokens[key] = (now + TOKEN_CACHE_S, u)
            for k in [k for k, v in self._tokens.items() if v[0] <= now]:
                self._tokens.pop(k, None)
        return u

    def session(self, headers):
        """(Service for the verified user, Store)."""
        u = self.authenticate(headers)
        store = Store(self.client())
        config = store.settings_asset()
        uid = u["id"]["id"]
        if u["authority"] == "TENANT_ADMIN":
            role = "admin"
        else:
            roles = config[1].get("cmms_roles") if isinstance(config[1].get("cmms_roles"), dict) else {}
            role = (roles.get(uid) or {}).get("role") or ""
            if role not in R.CUSTOMER_ROLES:
                raise HttpError(403, "You have no maintenance role yet. Ask the maintenance administrator to give you one.")
        user = User(id=uid, email=u.get("email") or "", name=user_name(u), authority=u["authority"],
                    customer_id=(u.get("customerId") or {}).get("id") or "", role=role)
        return Service(store, user, config, self.uploads), store

    # ------------------------------------------------------------------ request handling
    def handle(self, method, raw_path, headers, read_body):
        """-> (status, headers dict, body bytes). read_body(limit) returns the request body or raises HttpError(413)."""
        url = urlparse(raw_path)
        path = url.path.rstrip("/")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            for attempt in (0, 1):
                try:
                    return self._route(method, path[len(PREFIX):], query, headers, read_body)
                except StoreError as exc:
                    # the service session may have been revoked (ThingsBoard restart): log in again once
                    if attempt == 0 and "HTTP 401" in str(exc):
                        self.client(fresh=True)
                        continue
                    raise
        except HttpError as exc:
            return self._json(exc.status, {"ok": False, "error": str(exc)})
        except R.Forbidden as exc:
            return self._json(403, {"ok": False, "error": str(exc)})
        except NotFound as exc:
            return self._json(404, {"ok": False, "error": str(exc)})
        except ConflictError as exc:
            return self._json(409, {"ok": False, "error": str(exc)})
        except (Invalid, TransitionError) as exc:
            return self._json(400, {"ok": False, "error": str(exc)})
        except StoreError as exc:
            log.error("ThingsBoard error on %s %s: %s", method, path, exc)
            return self._json(502, {"ok": False, "error": "ThingsBoard rejected the change; nothing more was saved. Try again."})
        except Exception:
            log.exception("CMMS API failure on %s %s", method, path)
            return self._json(500, {"ok": False, "error": "Internal error; the administrator has been logged the details"})

    def _route(self, method, path, query, headers, read_body):
        if method == "GET" and path == "/state":
            svc, _ = self.session(headers)
            return self._json(200, dict(svc.state(), ok=True))
        if method == "GET" and path == "/users":
            svc, _ = self.session(headers)
            return self._json(200, dict(svc.users_view(), ok=True))
        if method == "GET" and path == "/profiles":
            svc, _ = self.session(headers)
            return self._json(200, dict(svc.profiles_view(), ok=True))
        m = re.fullmatch(r"/files/([0-9a-fA-F-]{36})", path)
        if method == "GET" and m:
            svc, store = self.session(headers)
            if not svc.visible_file(m.group(1)):
                raise NotFound("Document not found")
            data, ctype = store.download_resource(m.group(1))
            name = query.get("name") or "document"
            return 200, {"Content-Type": ctype, "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
                         "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}, data
        if method == "POST" and path == "/upload":
            return self._upload(query, headers, read_body)
        m = re.fullmatch(r"/action/([a-z_]+)", path)
        if method == "POST" and m:
            svc, _ = self.session(headers)
            try:
                body = json.loads(read_body(MAX_JSON).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                raise Invalid("Request body must be JSON")
            return self._json(200, dict(svc.run(m.group(1), body), ok=True))
        raise NotFound(f"No such endpoint: {method} {path}")

    def _upload(self, query, headers, read_body):
        svc, store = self.session(headers)
        purpose = query.get("purpose")
        if purpose not in ("attachment", "document"):
            raise Invalid("purpose must be attachment or document")
        svc.require("upload_" + purpose)
        name = (query.get("name") or "").strip().replace("/", "_").replace("\\", "_")[:200]
        if not name:
            raise Invalid("File name missing")
        limit = int(float(svc.settings.raw["max_upload_mb"]) * 1048576)
        data = read_body(limit)
        if not data:
            raise Invalid("The file is empty")
        for rid in self.uploads.expired():
            try:
                store.delete_resource(rid)
            except StoreError as exc:
                log.warning("could not delete unused upload %s: %s", rid, exc)
        rid = store.upload_resource(name, data, headers.get("Content-Type"), name)
        meta = {"id": rid, "title": name, "file": name, "size": len(data), "uploaded_by": svc.user.name, "uploaded_at": int(time.time() * 1000)}
        self.uploads.add(rid, svc.user, purpose, meta)
        return self._json(200, dict(meta, ok=True))

    @staticmethod
    def _json(status, obj):
        return status, {"Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}, \
            json.dumps(obj).encode("utf-8")


_api = None


def default_api():
    """Api with the service account of thingsboard/.env (created on first use)."""
    global _api
    if _api is None:
        from infra_reports.config import load_settings
        from infra_reports.tb_client import ThingsBoardClient
        _api = Api(lambda: ThingsBoardClient.connect(load_settings()))
    return _api
