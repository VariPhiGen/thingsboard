"""Minimal ThingsBoard REST client: timeouts, retries, pagination, explicit tenant."""
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ConfigError

log = logging.getLogger(__name__)

PAGE_SIZE = 100
ALARM_PAGE_SIZE = 1000
# Raw-history request limit per key; a day of the busiest key today is ~21k samples
HISTORY_LIMIT = 500_000
# How far back to look for the "latest" value of a key when reporting on a past day
LATEST_LOOKBACK_MS = 365 * 24 * 3600 * 1000


class ThingsBoardError(RuntimeError):
    """ThingsBoard could not be reached or returned an unexpected response."""


def build_session(retries=3):
    """requests.Session that retries connection errors and 429/5xx with backoff."""
    retry = Retry(
        total=retries, connect=retries, read=retries, status=retries,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class ThingsBoardClient:
    def __init__(self, base_url, session, timeout=60.0):
        self.base_url = base_url
        self.session = session
        self.timeout = timeout
        self._headers = {}

    # ------------------------------------------------------------------ auth
    @classmethod
    def connect(cls, settings, session=None):
        """Find a reachable ThingsBoard URL and authenticate as the configured tenant."""
        session = session or build_session(settings.http_retries)
        if settings.tb_tenant_user and settings.tb_tenant_pass:
            mode = "tenant"
            user, password = settings.tb_tenant_user, settings.tb_tenant_pass
        elif settings.tb_sysadmin_user and settings.tb_sysadmin_pass:
            if not settings.tb_tenant_id:
                raise ConfigError("TB_TENANT_ID is required when logging in with sysadmin credentials")
            mode = "sysadmin"
            user, password = settings.tb_sysadmin_user, settings.tb_sysadmin_pass
        else:
            raise ConfigError("ThingsBoard credentials missing: set TB_TENANT_USER/TB_TENANT_PASS "
                              "(preferred) or TB_SYSADMIN_USER/TB_SYSADMIN_PASS with TB_TENANT_ID")

        errors = []
        for base_url in settings.tb_urls:
            client = cls(base_url, session, settings.http_timeout)
            try:
                # Probe candidates once each; retries apply to the API calls that follow
                token = client._login(user, password, probe=True)
            except ThingsBoardError as exc:
                errors.append(f"{base_url}: {exc}")
                continue
            client._headers = {"X-Authorization": f"Bearer {token}"}
            if mode == "sysadmin":
                client._impersonate_tenant(settings.tb_tenant_id)
            log.info("Connected to ThingsBoard at %s (%s login)", base_url, mode)
            return client
        raise ThingsBoardError("Could not log in to ThingsBoard: " + "; ".join(errors))

    def _login(self, user, password, probe=False):
        poster = requests.post if probe else self.session.post
        try:
            res = poster(f"{self.base_url}/api/auth/login",
                                    json={"username": user, "password": password}, timeout=(3, 10))
        except requests.RequestException as exc:
            raise ThingsBoardError(f"unreachable ({exc.__class__.__name__})") from exc
        if res.status_code != 200:
            raise ThingsBoardError(f"login failed with HTTP {res.status_code}")
        return res.json()["token"]

    def _impersonate_tenant(self, tenant_id):
        """Sysadmin -> token of the first TENANT_ADMIN user of the configured tenant."""
        users = self._get(f"/api/tenant/{tenant_id}/users", {"pageSize": PAGE_SIZE, "page": 0})["data"]
        admins = sorted((u for u in users if u.get("authority") == "TENANT_ADMIN"), key=lambda u: u["email"])
        if not admins:
            raise ThingsBoardError(f"Tenant {tenant_id} has no TENANT_ADMIN user to read data as")
        token = self._get(f"/api/user/{admins[0]['id']['id']}/token")["token"]
        self._headers = {"X-Authorization": f"Bearer {token}"}
        log.warning("Reading ThingsBoard data via sysadmin impersonation; configure TB_TENANT_USER/TB_TENANT_PASS "
                    "for a dedicated read-only account instead")

    # ------------------------------------------------------------------ http
    def _get(self, path, params=None):
        try:
            res = self.session.get(f"{self.base_url}{path}", params=params, headers=self._headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ThingsBoardError(f"GET {path} failed: {exc}") from exc
        if res.status_code != 200:
            raise ThingsBoardError(f"GET {path} returned HTTP {res.status_code}: {res.text[:200]}")
        return res.json()

    def _paged(self, path, params=None, page_size=PAGE_SIZE):
        page = 0
        while True:
            data = self._get(path, {**(params or {}), "pageSize": page_size, "page": page})
            yield from data.get("data", [])
            if not data.get("hasNext"):
                return
            page += 1

    # ------------------------------------------------------------------ data
    def devices(self):
        return list(self._paged("/api/tenant/devices"))

    def attributes(self, device_id):
        return {a["key"]: a["value"] for a in self._get(f"/api/plugins/telemetry/DEVICE/{device_id}/values/attributes")}

    def timeseries_keys(self, device_id):
        return self._get(f"/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries")

    def latest(self, device_id, keys, end_ts=None):
        """{key: (ts, value)} of the newest sample per key (at or before end_ts when given)."""
        if not keys:
            return {}
        params = {"keys": ",".join(keys)}
        if end_ts is not None:
            params.update(startTs=end_ts - LATEST_LOOKBACK_MS, endTs=end_ts, limit=1, orderBy="DESC")
        raw = self._get(f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries", params)
        return {k: (v[0]["ts"], v[0]["value"]) for k, v in raw.items() if v}

    def history(self, device_id, keys, start_ts, end_ts):
        """{key: [{'ts', 'value'}, ...]} raw samples in [start_ts, end_ts)."""
        if not keys:
            return {}
        raw = self._get(f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries", {
            "keys": ",".join(keys), "startTs": start_ts, "endTs": end_ts, "limit": HISTORY_LIMIT, "orderBy": "ASC",
        })
        for key, points in raw.items():
            if len(points) >= HISTORY_LIMIT:
                log.warning("History of %s/%s hit the %d-sample limit; statistics may be incomplete",
                            device_id, key, HISTORY_LIMIT)
        return raw

    def alarms(self, device_id, start_ts=None, end_ts=None, active_only=False):
        """All alarms of a device: currently active ones, or the ones created in [start_ts, end_ts)."""
        params = {"searchStatus": "ACTIVE"} if active_only else {"startTime": start_ts, "endTime": end_ts}
        return list(self._paged(f"/api/alarm/DEVICE/{device_id}", params, page_size=ALARM_PAGE_SIZE))
