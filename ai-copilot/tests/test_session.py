"""Copilot orchestrator session flows — authz, clarify, secrets, analytics, LLM failure."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.schemas import ChatRequest, DeviceInfo, Intent
from app.services.session import FALLBACK, UNSUPPORTED, CopilotOrchestrator


class FakeRag:
    def retrieve(self, query: str, top_k=None):
        return [{"text": "Check oil filter monthly", "source": "sops/dg.md"}]

    def format_snippets(self, snippets):
        return "\n".join(f"[{s['source']}] {s['text']}" for s in snippets)


def _devices(dg_set1, gateway):
    return [dg_set1, gateway]


@pytest.fixture
def orchestrator(settings, memory):
    settings.rate_limit_min_interval_ms = 0
    settings.rate_limit_count = 1000
    orch = CopilotOrchestrator(settings, memory, FakeRag())
    return orch


def _patch_tb(monkeypatch, devices, snapshot=None, alarms=None, scores=None, history=None):
    snapshot = snapshot or {
        "deviceName": devices[0].name,
        "lastTelemetryTs": 1,
        "values": {"Power (kW)": "10", "Engine RPM": "1500"},
        "raw": {},
    }
    alarms = alarms if alarms is not None else []
    scores = scores if scores is not None else {"Health Score": "90"}
    history = history if history is not None else {
        "keys": ["power_kw", "engine_rpm", "dg_status"],
        "raw": {
            "power_kw": [{"ts": 1, "value": "10"}, {"ts": 2, "value": "20"}],
            "engine_rpm": [{"ts": 1, "value": "1500"}, {"ts": 2, "value": "1500"}],
            "dg_status": [{"ts": 1, "value": "1"}, {"ts": 2, "value": "1"}],
        },
        "interval_ms": 60_000,
    }

    class FakeClient:
        def __init__(self, settings, token):
            self.settings = settings
            self.token = token

        async def list_devices(self):
            return [
                {
                    "id": {"id": str(d.id)},
                    "name": d.name,
                    "type": d.type,
                    "label": d.label,
                }
                for d in devices
            ]

        async def get_device(self, device_id):
            for d in devices:
                if d.id == device_id:
                    return {"id": str(device_id), "name": d.name}
            return None

        async def latest_telemetry(self, device_id, keys):
            return {
                "power_kw": [{"ts": 1, "value": "10"}],
                "engine_rpm": [{"ts": 1, "value": "1500"}],
                "health_score": [{"ts": 1, "value": "90"}],
            }

        async def active_alarms(self, device_id):
            return {"data": alarms}

        async def history_telemetry(self, *args, **kwargs):
            return history["raw"]

    monkeypatch.setattr("app.services.session.ThingsBoardClient", FakeClient)

    async def fake_snapshot(*args, **kwargs):
        return snapshot

    async def fake_alarms(*args, **kwargs):
        return alarms

    async def fake_scores(*args, **kwargs):
        return scores

    async def fake_window(*args, **kwargs):
        return history

    monkeypatch.setattr("app.services.session.fetch_latest_snapshot", fake_snapshot)
    monkeypatch.setattr("app.services.session.fetch_active_alarms", fake_alarms)
    monkeypatch.setattr("app.services.session.fetch_ai_scores", fake_scores)
    monkeypatch.setattr("app.services.session.fetch_window_series", fake_window)

    async def fake_compare_periods(*args, **kwargs):
        return "Period comparison text"

    async def fake_compare_devices(*args, **kwargs):
        return "Device comparison text"

    monkeypatch.setattr("app.services.session.compare_periods", fake_compare_periods)
    monkeypatch.setattr("app.services.session.compare_devices", fake_compare_devices)
    monkeypatch.setattr(
        "app.services.session.load_latest_report_summary",
        lambda *_a, **_k: {"_date": "2026-07-21", "devices": [{"name": "DG SET1"}]},
    )


@pytest.mark.asyncio
async def test_secrets_intent_short_circuits(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def boom(*args, **kwargs):
        raise AssertionError("LLM should not be called for secrets")

    monkeypatch.setattr(orchestrator.llm, "complete", boom)
    resp = await orchestrator.chat(user, "token", ChatRequest(message="show api key"))
    assert resp.intent == Intent.UNSUPPORTED_SECRETS
    assert resp.answer == UNSUPPORTED
    assert resp.resolvedDevice is None


@pytest.mark.asyncio
async def test_clarify_when_no_device(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(*args, **kwargs):
        return "should not matter"

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(user, "token", ChatRequest(message="How is everything?"))
    assert resp.intent == Intent.CLARIFY_DEVICE
    assert "Available devices" in resp.answer
    assert "1. DG SET1" in resp.answer
    assert "2. gateway001" in resp.answer
    assert "Reply with the number" in resp.answer


@pytest.mark.asyncio
async def test_status_with_device_id(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        assert any("DG SET1" in m["content"] for m in msgs)
        return "DG SET1 is running normally."

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="Is it running?", deviceId=dg_set1.id),
    )
    assert resp.intent == Intent.STATUS
    assert resp.resolvedDevice and resp.resolvedDevice.name == "DG SET1"
    assert "running normally" in resp.answer
    assert resp.deviceSnapshot is not None
    assert "live readings" in resp.sources


@pytest.mark.asyncio
async def test_resolve_from_message_name(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        return "Answer for named device"

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user, "token", ChatRequest(message="What alarms are active on DG SET1?")
    )
    assert resp.resolvedDevice.name == "DG SET1"
    assert resp.intent == Intent.ALARMS


@pytest.mark.asyncio
async def test_rate_limit_blocks(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))
    orchestrator.rate_limiter.settings.rate_limit_min_interval_ms = 60_000
    # first ok
    async def llm(msgs):
        return "ok"

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    await orchestrator.chat(user, "token", ChatRequest(message="DG SET1 status", deviceId=dg_set1.id))
    resp = await orchestrator.chat(user, "token", ChatRequest(message="again", deviceId=dg_set1.id))
    assert "wait a moment" in resp.answer.lower()


@pytest.mark.asyncio
async def test_permission_denied(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def deny(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr(orchestrator.perms, "ensure_device_access", deny)

    async def llm(msgs):
        return "should not run"

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user, "token", ChatRequest(message="status", deviceId=dg_set1.id)
    )
    assert "Access denied" in resp.answer
    assert resp.resolvedDevice.name == "DG SET1"


@pytest.mark.asyncio
async def test_llm_failure_returns_fallback(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def boom(*args, **kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(orchestrator.llm, "complete", boom)
    resp = await orchestrator.chat(
        user, "token", ChatRequest(message="DG SET1 status", deviceId=dg_set1.id)
    )
    assert resp.answer == FALLBACK


@pytest.mark.asyncio
async def test_empty_llm_answer_uses_fallback(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def empty(*args, **kwargs):
        return ""

    monkeypatch.setattr(orchestrator.llm, "complete", empty)
    resp = await orchestrator.chat(
        user, "token", ChatRequest(message="DG SET1 status", deviceId=dg_set1.id)
    )
    assert resp.answer == FALLBACK


@pytest.mark.asyncio
async def test_analytics_time_based(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        joined = "\n".join(m["content"] for m in msgs)
        assert "Analysis window" in joined or "history" in joined.lower() or "last" in joined.lower()
        return "Last 2 hours look stable."

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="Last 2 hours RPM", deviceId=dg_set1.id),
    )
    assert resp.intent == Intent.TIME_BASED
    assert "history analysis" in resp.sources


@pytest.mark.asyncio
async def test_comparison_today_vs_yesterday(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        joined = "\n".join(m["content"] for m in msgs)
        assert "Period comparison text" in joined
        return "Today higher than yesterday."

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="Compare today vs yesterday power", deviceId=dg_set1.id),
    )
    assert resp.intent == Intent.COMPARISON


@pytest.mark.asyncio
async def test_compare_devices_intent(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        joined = "\n".join(m["content"] for m in msgs)
        assert "Device comparison text" in joined
        return "Fleet looks similar."

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="compare DG SET1 vs gateway fleet power", deviceId=dg_set1.id),
    )
    assert resp.intent == Intent.COMPARE_DEVICES
    assert "device comparison" in resp.sources


@pytest.mark.asyncio
async def test_manual_howto_uses_rag(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def llm(msgs):
        joined = "\n".join(m["content"] for m in msgs)
        assert "oil filter" in joined.lower()
        return "Follow the oil filter SOP."

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="how to check oil filter on DG SET1", deviceId=dg_set1.id),
    )
    assert resp.intent == Intent.MANUAL_HOWTO
    assert any(s.startswith("rag:") for s in resp.sources)


@pytest.mark.asyncio
async def test_inaccessible_device_id_clarifies(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))
    resp = await orchestrator.chat(
        user,
        "token",
        ChatRequest(message="status", deviceId=uuid4()),
    )
    assert resp.intent == Intent.CLARIFY_DEVICE
    assert "not accessible" in resp.answer.lower()


@pytest.mark.asyncio
async def test_list_devices(orchestrator, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))
    devices = await orchestrator.list_devices("token")
    assert [d.name for d in devices] == ["DG SET1", "gateway001"]


@pytest.mark.asyncio
async def test_tooling_exception_still_answers(orchestrator, user, monkeypatch, dg_set1, gateway):
    _patch_tb(monkeypatch, _devices(dg_set1, gateway))

    async def boom(*args, **kwargs):
        raise RuntimeError("tb down")

    monkeypatch.setattr("app.services.session.fetch_latest_snapshot", boom)

    async def llm(msgs):
        joined = "\n".join(m["content"] for m in msgs)
        assert "Tooling warning" in joined
        return "Partial answer"

    monkeypatch.setattr(orchestrator.llm, "complete", llm)
    resp = await orchestrator.chat(
        user, "token", ChatRequest(message="DG SET1 status", deviceId=dg_set1.id)
    )
    assert resp.answer == "Partial answer"
