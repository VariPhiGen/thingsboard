"""Auth header extraction, API schemas, and FastAPI chat routes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.jwt_tb import _extract_bearer, get_tb_user
from app.models.schemas import ChatRequest, ChatResponse, Intent
from app.api import chat as chat_api


def test_extract_bearer_from_authorization():
    assert _extract_bearer("Bearer abc.def", None) == "abc.def"
    assert _extract_bearer(None, "Bearer xyz") == "xyz"
    assert _extract_bearer("raw-token", None) == "raw-token"


def test_extract_bearer_prefers_x_authorization():
    # x_authorization is first arg in get_tb_user call order; helper takes *headers
    assert _extract_bearer("Bearer first", "Bearer second") == "first"


def test_extract_bearer_missing():
    with pytest.raises(HTTPException) as exc:
        _extract_bearer(None, None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_tb_user_success(monkeypatch, settings):
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "id": {"id": str(uuid4())},
                "tenantId": {"id": str(uuid4())},
                "customerId": {"id": str(uuid4())},
                "email": "op@example.com",
                "authority": "TENANT_ADMIN",
                "firstName": "Op",
                "lastName": "User",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, headers=None):
            assert path == "/api/auth/user"
            assert "Bearer" in headers["X-Authorization"]
            return FakeResp()

    monkeypatch.setattr("app.auth.jwt_tb.httpx.AsyncClient", FakeClient)
    user, token = await get_tb_user(
        authorization="Bearer tok",
        x_authorization=None,
        settings=settings,
    )
    assert token == "tok"
    assert user.email == "op@example.com"


@pytest.mark.asyncio
async def test_get_tb_user_unauthorized(monkeypatch, settings):
    class FakeResp:
        status_code = 401

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, headers=None):
            return FakeResp()

    monkeypatch.setattr("app.auth.jwt_tb.httpx.AsyncClient", FakeClient)
    with pytest.raises(HTTPException) as exc:
        await get_tb_user(authorization="Bearer bad", x_authorization=None, settings=settings)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_tb_user_bad_gateway(monkeypatch, settings):
    class FakeResp:
        status_code = 500

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, headers=None):
            return FakeResp()

    monkeypatch.setattr("app.auth.jwt_tb.httpx.AsyncClient", FakeClient)
    with pytest.raises(HTTPException) as exc:
        await get_tb_user(authorization="Bearer x", x_authorization=None, settings=settings)
    assert exc.value.status_code == 502


def test_chat_request_validation():
    with pytest.raises(ValidationError):
        ChatRequest(message="")
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)
    ok = ChatRequest(message="ok", deviceId=uuid4())
    assert ok.message == "ok"


def test_chat_routes_with_dependency_overrides():
    app = FastAPI()
    app.include_router(chat_api.router)

    class Orch:
        async def list_devices(self, token):
            return []

        async def chat(self, user, token, body):
            return ChatResponse(
                conversationId=uuid4(),
                answer="hi",
                timestamp=1,
                intent=Intent.GENERAL,
                sources=[],
            )

    app.state.orchestrator = Orch()

    async def fake_user():
        from app.models.schemas import TbUser

        return TbUser(id=uuid4(), tenantId=uuid4()), "tok"

    app.dependency_overrides[chat_api.get_tb_user] = fake_user
    client = TestClient(app)
    r = client.get("/v1/devices")
    assert r.status_code == 200
    assert r.json() == []
    r = client.post("/v1/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json()["answer"] == "hi"


def test_chat_routes_map_permission_and_errors():
    app = FastAPI()
    app.include_router(chat_api.router)

    class Orch:
        async def list_devices(self, token):
            raise PermissionError("denied")

        async def chat(self, user, token, body):
            raise RuntimeError("boom")

    app.state.orchestrator = Orch()

    async def fake_user():
        from app.models.schemas import TbUser

        return TbUser(id=uuid4(), tenantId=uuid4()), "tok"

    app.dependency_overrides[chat_api.get_tb_user] = fake_user
    client = TestClient(app)
    assert client.get("/v1/devices").status_code == 403
    assert client.post("/v1/chat", json={"message": "hello"}).status_code == 500
