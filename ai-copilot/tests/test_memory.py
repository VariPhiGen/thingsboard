"""Conversation memory and rate limiter edge cases."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from app.config import Settings
from app.services.memory import ConversationMemory, RateLimiter


def test_ensure_conversation_id_generates_and_reuses(memory):
    a = memory.ensure_conversation_id(None)
    b = memory.ensure_conversation_id(a)
    assert a == b
    assert a is not None


def test_append_and_get_messages(memory):
    cid = memory.ensure_conversation_id(None)
    memory.append(cid, "USER", "hi")
    memory.append(cid, "ASSISTANT", "hello")
    msgs = memory.get_messages(cid)
    assert [m.role for m in msgs] == ["USER", "ASSISTANT"]
    assert msgs[0].content == "hi"


def test_append_empty_content_ignored(memory):
    cid = memory.ensure_conversation_id(None)
    memory.append(cid, "USER", "")
    assert memory.get_messages(cid) == []


def test_memory_max_messages_trim(settings):
    settings.memory_max_messages = 2
    mem = ConversationMemory(settings)
    cid = mem.ensure_conversation_id(None)
    mem.append(cid, "USER", "1")
    mem.append(cid, "ASSISTANT", "2")
    mem.append(cid, "USER", "3")
    msgs = mem.get_messages(cid)
    assert [m.content for m in msgs] == ["2", "3"]


def test_memory_ttl_expires(settings, monkeypatch):
    settings.memory_ttl_seconds = 10
    mem = ConversationMemory(settings)
    cid = mem.ensure_conversation_id(None)
    mem.append(cid, "USER", "old")
    # force stale updated_at
    key = str(cid)
    mem._local[key].updated_at = time.time() - 100
    assert mem.get_messages(cid) == []


def test_unknown_conversation_returns_empty(memory):
    assert memory.get_messages(uuid4()) == []


def test_rate_limiter_allows_then_blocks_min_interval():
    settings = Settings(rate_limit_min_interval_ms=5000, rate_limit_count=100, rate_limit_window_ms=60_000)
    limiter = RateLimiter(settings)
    uid = uuid4()
    limiter.check(uid, None)
    with pytest.raises(RuntimeError, match="wait a moment"):
        limiter.check(uid, None)


def test_rate_limiter_window_count():
    settings = Settings(rate_limit_min_interval_ms=0, rate_limit_count=2, rate_limit_window_ms=60_000)
    limiter = RateLimiter(settings)
    uid = uuid4()
    limiter.check(uid)
    limiter.check(uid)
    with pytest.raises(RuntimeError, match="limit reached"):
        limiter.check(uid)


def test_rate_limiter_keys_by_device():
    settings = Settings(rate_limit_min_interval_ms=5000, rate_limit_count=100, rate_limit_window_ms=60_000)
    limiter = RateLimiter(settings)
    uid = uuid4()
    d1, d2 = uuid4(), uuid4()
    limiter.check(uid, d1)
    # different device key should not hit min-interval for d1
    limiter.check(uid, d2)
