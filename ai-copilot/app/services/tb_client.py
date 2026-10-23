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

    async def list_devices(self, page_size: int = 100, customer_id: str | None = None) -> list[dict[str, Any]]:
        params = {"pageSize": page_size, "page": 0, "sortProperty": "name", "sortOrder": "ASC"}
        candidate_paths: list[str] = []
        if customer_id:
            candidate_paths.extend([
                f"/api/customer/{customer_id}/deviceInfos",
                f"/api/customer/{customer_id}/devices",
            ])
        candidate_paths.extend([
            "/api/tenant/devices",
            "/api/tenant/deviceInfos",
            "/api/user/devices",
        ])
        for path in candidate_paths:
            try:
                data = await self._request_get_allow_forbidden(path, params)
                if isinstance(data, dict) and "data" in data and data["data"]:
                    return list(data.get("data") or [])
            except PermissionError:
                continue
            except Exception:
                continue

        # If not found yet, check /api/auth/user to discover customerId
        try:
            user_info = await self._get("/api/auth/user")
            if user_info and isinstance(user_info, dict):
                cid = (user_info.get("customerId") or {}).get("id")
                if cid and cid != "13814000-1dd2-11b2-8080-808080808080":
                    for path in (f"/api/customer/{cid}/deviceInfos", f"/api/customer/{cid}/devices"):
                        try:
                            data = await self._request_get_allow_forbidden(path, params)
                            if isinstance(data, dict) and "data" in data and data["data"]:
                                return list(data.get("data") or [])
                        except Exception:
                            continue
        except Exception:
            pass

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

    async def latest_telemetry(self, device_id: UUID, keys: list[str] | None = None) -> dict[str, Any]:
        params = {"keys": ",".join(keys)} if keys else None
        raw = await self._get(
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params,
        )
        return raw or {}

    async def history_telemetry(
        self,
        device_id: UUID,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 50,
        interval: int | None = None,
        agg: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "keys": ",".join(keys),
            "startTs": start_ts,
            "endTs": end_ts,
            "limit": limit,
            "orderBy": "ASC",
        }
        if interval and agg:
            params["interval"] = interval
            params["agg"] = agg
        else:
            params["agg"] = "NONE"
        raw = await self._get(
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params,
        )
        return raw or {}

    async def active_alarms(self, device_id: UUID, page_size: int = 50) -> dict[str, Any]:
        raw = await self._get(
            f"/api/alarm/DEVICE/{device_id}",
            {"searchStatus": "ACTIVE", "pageSize": page_size, "page": 0},
        )
        return raw or {"data": [], "totalElements": 0}
