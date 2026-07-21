from __future__ import annotations

import httpx
from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.models.schemas import TbUser


def _extract_bearer(*headers: str | None) -> str:
    for value in headers:
        if not value:
            continue
        raw = value.strip()
        if raw.lower().startswith("bearer "):
            return raw.split(" ", 1)[1].strip()
        return raw
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")


async def get_tb_user(
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None, alias="X-Authorization"),
    settings: Settings = Depends(get_settings),
) -> tuple[TbUser, str]:
    token = _extract_bearer(x_authorization, authorization)
    async with httpx.AsyncClient(base_url=settings.tb_base_url, timeout=20.0) as client:
        resp = await client.get("/api/auth/user", headers={"X-Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if resp.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ThingsBoard auth failed")
    data = resp.json()
    user = TbUser(
        id=data["id"]["id"],
        tenantId=data["tenantId"]["id"],
        customerId=(data.get("customerId") or {}).get("id"),
        email=data.get("email"),
        authority=data.get("authority"),
        firstName=data.get("firstName"),
        lastName=data.get("lastName"),
    )
    return user, token
