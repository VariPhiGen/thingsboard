from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.config import Settings


class ThingsBoardClient:
    def __init__(self, settings: Settings, token: str):
        self.settings = settings
        self.token = token
        self._headers = {
            "X-Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(base_url=self.settings.tb_base_url, timeout=30.0) as client:
            resp = await client.get(path, headers=self._headers, params=params)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized")
        if resp.status_code == 403:
            raise PermissionError("Forbidden")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"TB GET {path} failed: {resp.status_code} {resp.text[:300]}")
        if not resp.content:
            return None
        return resp.json()

    async def list_devices(self, page_size: int = 100) -> list[dict[str, Any]]:
        params = {"pageSize": page_size, "page": 0, "sortProperty": "name", "sortOrder": "ASC"}
        for path in ("/api/tenant/devices", "/api/user/devices", "/api/tenant/deviceInfos"):
            try:
                data = await self._request_get_allow_forbidden(path, params)
                if isinstance(data, dict) and "data" in data:
                    return list(data.get("data") or [])
            except PermissionError:
                continue
            except Exception:
                continue
        return []

    async def _request_get_allow_forbidden(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(base_url=self.settings.tb_base_url, timeout=30.0) as client:
            resp = await client.get(path, headers=self._headers, params=params)
        if resp.status_code in (401, 403):
            raise PermissionError("Forbidden")
        if resp.status_code >= 400:
            raise RuntimeError(f"TB GET {path} failed: {resp.status_code}")
        return resp.json() if resp.content else None

    async def get_device(self, device_id: UUID) -> dict[str, Any] | None:
        return await self._get(f"/api/device/{device_id}")

    async def latest_telemetry(self, device_id: UUID, keys: list[str]) -> dict[str, Any]:
        raw = await self._get(
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            {"keys": ",".join(keys)},
        )
        return raw or {}

    async def history_telemetry(
        self,
        device_id: UUID,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 50,
    ) -> dict[str, Any]:
        raw = await self._get(
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            {
                "keys": ",".join(keys),
                "startTs": start_ts,
                "endTs": end_ts,
                "limit": limit,
                "agg": "NONE",
            },
        )
        return raw or {}

    async def active_alarms(self, device_id: UUID, page_size: int = 50) -> dict[str, Any]:
        raw = await self._get(
            f"/api/alarm/DEVICE/{device_id}",
            {"searchStatus": "ACTIVE", "pageSize": page_size, "page": 0},
        )
        return raw or {"data": [], "totalElements": 0}
