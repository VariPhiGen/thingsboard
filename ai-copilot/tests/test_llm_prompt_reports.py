"""LLM language softening, prompt builder, reports, RAG chunking, permissions."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.config import Settings
from app.models.schemas import ChatMessage, Intent
from app.services.llm import LlmService, soften_operator_language
from app.services.permissions import PermissionManager
from app.services.prompt_builder import SYSTEM_PROMPT, build_messages
from app.services.rag import RagService
from app.services.tools.reports import format_report_context, load_latest_report_summary


def test_soften_replaces_banned_terms():
    text = "ThingsBoard TB IoT platform telemetry API says OK"
    out = soften_operator_language(text)
    assert "ThingsBoard" not in out
    assert "IoT platform" not in out
    assert "telemetry" not in out.lower() or "live readings" in out.lower()
    assert "API" not in out or "system" in out
    assert "the dashboard" in out


def test_soften_none_and_empty():
    assert soften_operator_language("") == ""
    assert soften_operator_language(None) == ""


@pytest.mark.asyncio
async def test_llm_complete_without_api_key(settings):
    settings.openai_api_key = ""
    llm = LlmService(settings)
    out = await llm.complete([{"role": "user", "content": "hi"}])
    assert "not configured" in out.lower()


@pytest.mark.asyncio
async def test_llm_complete_softens_model_output(settings, monkeypatch):
    settings.openai_api_key = "sk-test"

    class FakeMsg:
        content = "ThingsBoard telemetry API looks fine"

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    llm = LlmService(settings)
    llm._client = FakeClient()
    out = await llm.complete([{"role": "user", "content": "status"}])
    assert "ThingsBoard" not in out
    assert "live readings" in out.lower() or "dashboard" in out.lower()


def test_build_messages_structure_and_history_cap():
    history = [ChatMessage(role="USER", content=f"q{i}") for i in range(12)]
    history += [ChatMessage(role="ASSISTANT", content=f"a{i}") for i in range(12)]
    msgs = build_messages(
        intent=Intent.STATUS,
        user_message="RPM?",
        history=history,
        grounding="Device: DG SET1",
        rag_snippets="[sop]\nCheck oil",
    )
    assert msgs[0]["role"] == "system"
    assert "Never say ThingsBoard" in SYSTEM_PROMPT or "NEVER say ThingsBoard" in SYSTEM_PROMPT
    assert "Do not use Markdown" in SYSTEM_PROMPT
    # last 8 history + system + final user context
    assert len(msgs) == 1 + 8 + 1
    assert "Operator question: RPM?" in msgs[-1]["content"]
    assert "Check oil" in msgs[-1]["content"]


def test_load_report_missing_dir(tmp_path):
    assert load_latest_report_summary(str(tmp_path / "missing")) is None


def test_load_report_skips_bad_json_uses_latest(tmp_path):
    bad = tmp_path / "2026-07-20"
    good = tmp_path / "2026-07-21"
    bad.mkdir()
    good.mkdir()
    (bad / "summary.json").write_text("{bad", encoding="utf-8")
    (good / "summary.json").write_text(
        json.dumps({"devices": [{"name": "DG SET1", "alarms": 1}]}),
        encoding="utf-8",
    )
    data = load_latest_report_summary(str(tmp_path))
    assert data is not None
    assert data["_date"] == "2026-07-21"
    assert data["devices"][0]["name"] == "DG SET1"


def test_format_report_context_variants():
    assert "No daily report" in format_report_context(None)
    text = format_report_context({"_date": "2026-07-21", "devices": [{"name": "DG SET1", "ok": True}]})
    assert "2026-07-21" in text and "DG SET1" in text
    text2 = format_report_context({"_date": "d", "devices": ["raw"]})
    assert "- raw" in text2
    text3 = format_report_context({"_date": "d", "devices": {"x": 1}})
    assert "x" in text3


def test_rag_chunk_short_and_long():
    assert RagService._chunk("hello") == ["hello"]
    chunks = RagService._chunk("x" * 2000, size=900, overlap=120)
    assert len(chunks) >= 2
    assert all(len(c) <= 900 for c in chunks)


def test_rag_format_snippets_empty_and_filled(settings):
    rag = RagService(settings)
    assert rag.format_snippets([]) == ""
    out = rag.format_snippets([{"source": "sops/dg.md", "text": "Check oil"}])
    assert "[sops/dg.md]" in out
    assert "Check oil" in out


def test_rag_retrieve_empty_query(settings):
    rag = RagService(settings)
    assert rag.retrieve("") == []


@pytest.mark.asyncio
async def test_permissions_skips_bad_items_and_ensures_access():
    class FakeClient:
        async def list_devices(self):
            return [
                {"id": {"id": str(uuid4())}, "name": "DG SET1", "type": "woodward_kg1500"},
                {"broken": True},
                {"id": {"id": str(uuid4())}, "name": None, "type": "gateway"},
            ]

        async def get_device(self, device_id):
            return None if str(device_id).startswith("0000") else {"id": str(device_id)}

    perms = PermissionManager()
    devices = await perms.list_accessible_devices(FakeClient())
    assert len(devices) == 2
    assert devices[1].name == "unnamed"

    ok = await perms.ensure_device_access(FakeClient(), uuid4())
    assert ok["id"]

    class DenyClient:
        async def get_device(self, device_id):
            return None

    with pytest.raises(PermissionError, match="not accessible"):
        await perms.ensure_device_access(DenyClient(), uuid4())
