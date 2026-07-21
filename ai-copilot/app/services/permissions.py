from __future__ import annotations

from uuid import UUID

from app.models.schemas import DeviceInfo
from app.services.tb_client import ThingsBoardClient


class PermissionManager:
    async def list_accessible_devices(self, client: ThingsBoardClient) -> list[DeviceInfo]:
        raw = await client.list_devices()
        out: list[DeviceInfo] = []
        for item in raw:
            try:
                out.append(
                    DeviceInfo(
                        id=item["id"]["id"],
                        name=item.get("name") or "unnamed",
                        type=item.get("type"),
                        label=item.get("label"),
                    )
                )
            except Exception:
                continue
        return out

    async def ensure_device_access(self, client: ThingsBoardClient, device_id: UUID) -> dict:
        device = await client.get_device(device_id)
        if not device:
            raise PermissionError("Device not found or not accessible")
        return device
