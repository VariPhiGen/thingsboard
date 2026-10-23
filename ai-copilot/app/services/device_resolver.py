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
    is_fleet: bool = False


FLEET_PATTERNS = [
    r"\b(sare|saare|sab|sabhi|har\s*ek|all|every)\s*(devices?|systems?|equipments?|plants?)\b",
    r"\b(fleet|overview|plant\s*summary|facility|plant\s*status|system\s*summary)\b",
    r"\b(list\s*(of\s*)?devices?|show\s*devices?|how\s*many\s*devices?)\b",
    r"^(hi|hello|namaste|hey|help|kya\s*status\s*hai|kaise\s*ho)\b",
]


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

        msg = (message or "").strip()
        lower_msg = msg.lower()

        # Check if user selected by number (e.g. "1", "2", "device 1", "#3")
        num_match = re.match(r"^(?:device\s*|#\s*)?(\d{1,2})$", lower_msg)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(devices):
                matched_device = devices[idx]
                return ResolveResult(matched_device, [matched_device], False)

        query = (device_query or "").strip()
        if not query and message:
            query = self._extract_device_mention(message, devices) or ""

        # If still no single device identified, check if it is a fleet / multi-device or general question
        if not query:
            for pattern in FLEET_PATTERNS:
                if re.search(pattern, lower_msg, re.I):
                    return ResolveResult(
                        device=None,
                        candidates=devices,
                        needs_clarification=False,
                        is_fleet=True,
                    )

            if len(devices) == 1:
                return ResolveResult(devices[0], devices, False)
            # Default to fleet overview rather than a dead-end blocker if user asked a general question
            return ResolveResult(
                device=None,
                candidates=devices,
                needs_clarification=False,
                is_fleet=True,
            )

        matches = self._match(devices, query)
        if len(matches) == 1:
            return ResolveResult(matches[0], matches, False)
        if not matches:
            # Fallback: check fleet patterns
            for pattern in FLEET_PATTERNS:
                if re.search(pattern, lower_msg, re.I):
                    return ResolveResult(device=None, candidates=devices, needs_clarification=False, is_fleet=True)
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
        dev_map = {d.name.lower(): d.name for d in devices if d.name}

        # Specific alias detection for Delhivery / Virtuoso facility devices:
        # 1. Fire Suppression UPS Room 2
        if re.search(r"\b(ups\s*room\s*2|ups\s*2|fire\s*ups\s*2|fire\s*suppression\s*ups\s*room\s*2|ups-2)\b", text):
            for d in devices:
                if "ups room 2" in (d.name or "").lower():
                    return d.name

        # 2. RO Plant System
        if re.search(r"\b(ro|ro\s*plant|ro\s*system|water\s*purifier|water\s*treatment|tds|water\s*plant|osmosis|permeate)\b", text):
            for d in devices:
                if "ro plant" in (d.name or "").lower() or (d.type and re.search(r"\bro\b", d.type.lower())):
                    return d.name

        # 3. Fire Suppression (Room 1)
        if re.search(r"\b(fire\s*suppression|fire\s*system|gas\s*suppression|ups\s*room\s*1\s*fire|cylinder\s*pressure|cylinders)\b", text):
            if "ups room 2" not in text and "ups 2" not in text:
                for d in devices:
                    if (d.name or "").lower() == "fire suppression":
                        return d.name

        # 4. LT Panels Gateway
        if re.search(r"\b(lt\s*panel|lt\s*panels|gateway|electrical\s*room|transformer|evm\s*charger|evm|fire\s*fighting\s*wall|sub\s*panels|panels)\b", text):
            for d in devices:
                if "lt panel" in (d.name or "").lower() or "gateway" in (d.name or "").lower():
                    return d.name

        # 5. DG Set 3
        if re.search(r"\b(dg\s*3|dg\s*set\s*3|dgset3|dg3|generator\s*3|set\s*3|set3)\b", text):
            for d in devices:
                if "dg set 3" in (d.name or "").lower():
                    return d.name

        # 6. DG Set 2
        if re.search(r"\b(dg\s*2|dg\s*set\s*2|dgset2|dg2|generator\s*2|set\s*2|set2)\b", text):
            for d in devices:
                if "dg set 2" in (d.name or "").lower():
                    return d.name

        # 7. DG SET1
        if re.search(r"\b(dg\s*1|dg\s*set\s*1|dgset1|dg1|generator\s*1|set\s*1|set1|dg\s*set1)\b", text):
            for d in devices:
                if "dg set1" in (d.name or "").lower() or "dg set 1" in (d.name or "").lower():
                    return d.name

        # Generic DG fallback if only "dg" or "generator" is mentioned
        if re.search(r"\b(dg|generator|genset)\b", text):
            for d in devices:
                if "dg set1" in (d.name or "").lower():
                    return d.name

        # Direct name match
        ranked = sorted(devices, key=lambda d: len(d.name or ""), reverse=True)
        for d in ranked:
            name = (d.name or "").lower()
            label = (d.label or "").lower()
            if name and re.search(rf"\b{re.escape(name)}\b", text):
                return d.name
            if label and re.search(rf"\b{re.escape(label)}\b", text):
                return d.label

        return None
