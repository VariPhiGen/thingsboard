from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Intent(str, Enum):
    STATUS = "status"
    ALARMS = "alarms"
    HISTORY = "history"
    AI_GUIDANCE = "ai_guidance"
    MANUAL_HOWTO = "manual_howto"
    COMPARE_DEVICES = "compare_devices"
    UNSUPPORTED_SECRETS = "unsupported_secrets"
    CLARIFY_DEVICE = "clarify_device"
    GENERAL = "general"


class ChatMessage(BaseModel):
    role: str
    content: str


class DeviceInfo(BaseModel):
    id: UUID
    name: str
    type: str | None = None
    label: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversationId: UUID | None = None
    deviceId: UUID | None = None
    deviceQuery: str | None = None
    dashboardId: UUID | None = None
    messages: list[ChatMessage] | None = None


class DeviceSnapshot(BaseModel):
    deviceName: str
    dashboardTitle: str | None = None
    lastTelemetryTs: int | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class AlarmInfo(BaseModel):
    severity: str | None = None
    type: str | None = None
    status: str | None = None
    details: str | None = None


class ChatResponse(BaseModel):
    conversationId: UUID
    answer: str
    timestamp: int
    resolvedDevice: DeviceInfo | None = None
    intent: Intent
    sources: list[str] = Field(default_factory=list)
    deviceSnapshot: DeviceSnapshot | None = None
    activeAlarms: list[AlarmInfo] = Field(default_factory=list)


class TbUser(BaseModel):
    id: UUID
    tenantId: UUID
    customerId: UUID | None = None
    email: str | None = None
    authority: str | None = None
    firstName: str | None = None
    lastName: str | None = None
