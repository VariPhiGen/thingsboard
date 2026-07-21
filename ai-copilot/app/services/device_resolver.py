from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.models.schemas import DeviceInfo


@dataclass
class ResolveResult:
    device: DeviceInfo | None
    candidates: list[DeviceInfo]
    needs_clarification: bool
    reason: str | None = None


class DeviceResolver:
    def resolve(
        self,
        devices: list[DeviceInfo],
        device_id: UUID | None = None,
        device_query: str | None = None,
        message: str | None = None,
    ) -> ResolveResult:
        by_id = {d.id: d for d in devices}
        if device_id is not None:
            device = by_id.get(device_id)
            if device is None:
                return ResolveResult(None, [], True, "Selected device is not accessible.")
            return ResolveResult(device, [device], False)

        query = (device_query or "").strip()
        if not query and message:
            query = self._extract_device_mention(message, devices) or ""

        if not query:
            if len(devices) == 1:
                return ResolveResult(devices[0], devices, False)
            return ResolveResult(None, devices[:8], True, "Which device should I use?")

        matches = self._match(devices, query)
        if len(matches) == 1:
            return ResolveResult(matches[0], matches, False)
        if not matches:
            return ResolveResult(None, devices[:8], True, f"No device matched '{query}'.")
        return ResolveResult(None, matches[:8], True, f"Multiple devices matched '{query}'.")

    def _match(self, devices: list[DeviceInfo], query: str) -> list[DeviceInfo]:
        q = query.lower().strip()
        exact = []
        partial = []
        for d in devices:
            names = [d.name or "", d.label or "", d.type or ""]
            lowered = [n.lower() for n in names if n]
            if any(n == q for n in lowered):
                exact.append(d)
            elif any(q in n or n in q for n in lowered):
                partial.append(d)
        return exact or partial

    def _extract_device_mention(self, message: str, devices: list[DeviceInfo]) -> str | None:
        text = message.lower()
        # Prefer longer names first
        ranked = sorted(devices, key=lambda d: len(d.name or ""), reverse=True)
        for d in ranked:
            name = (d.name or "").lower()
            label = (d.label or "").lower()
            if name and re.search(rf"\b{re.escape(name)}\b", text):
                return d.name
            if label and re.search(rf"\b{re.escape(label)}\b", text):
                return d.label
        # Common aliases
        if "dg set1" in text or "dgset1" in text or "set1" in text:
            return "DG SET1"
        if "gateway" in text:
            return "gateway001"
        return None
