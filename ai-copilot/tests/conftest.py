"""Shared fixtures for AI Copilot tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.models.schemas import DeviceInfo, TbUser
from app.services.memory import ConversationMemory
from app.services.rag import RagService


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        openai_api_key="",
        redis_url="",
        memory_ttl_seconds=1800,
        memory_max_messages=4,
        rate_limit_count=5,
        rate_limit_window_ms=60_000,
        rate_limit_min_interval_ms=0,
        reports_dir=str(tmp_path / "reports"),
        knowledge_dir=str(tmp_path / "knowledge"),
        rag_persist_dir=str(tmp_path / "chroma"),
        tb_base_url="http://tb.test",
    )


@pytest.fixture
def memory(settings) -> ConversationMemory:
    return ConversationMemory(settings)


@pytest.fixture
def rag(settings) -> RagService:
    return RagService(settings)


@pytest.fixture
def user() -> TbUser:
    return TbUser(
        id=uuid4(),
        tenantId=uuid4(),
        email="operator@example.com",
        authority="TENANT_ADMIN",
    )


@pytest.fixture
def dg_set1() -> DeviceInfo:
    return DeviceInfo(
        id=UUID("3877b730-81cb-11f1-a760-b3ba4cbe1b98"),
        name="DG SET1",
        type="woodward_kg1500",
        label="DG SET1",
    )


@pytest.fixture
def gateway() -> DeviceInfo:
    return DeviceInfo(
        id=UUID("4cfd4020-81c2-11f1-a760-b3ba4cbe1b98"),
        name="gateway001",
        type="gateway",
        label="Plant Gateway",
    )


@pytest.fixture
def fleet(dg_set1, gateway) -> list[DeviceInfo]:
    return [
        dg_set1,
        gateway,
        DeviceInfo(id=uuid4(), name="DG SET2", type="woodward_kg1500"),
        DeviceInfo(id=uuid4(), name="DG SET10", type="woodward_kg1500"),
    ]
