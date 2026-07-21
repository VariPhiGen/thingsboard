from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque
from uuid import UUID

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from app.config import Settings
from app.models.schemas import ChatMessage


@dataclass
class ConversationState:
    messages: Deque[ChatMessage] = field(default_factory=deque)
    updated_at: float = field(default_factory=time.time)


class ConversationMemory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = Lock()
        self._local: dict[str, ConversationState] = {}
        self._redis = None
        if settings.redis_url and redis is not None:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def ensure_conversation_id(self, conversation_id: UUID | None) -> UUID:
        return conversation_id or uuid.uuid4()

    def _key(self, conversation_id: UUID) -> str:
        return f"copilot:conv:{conversation_id}"

    def get_messages(self, conversation_id: UUID) -> list[ChatMessage]:
        if self._redis is not None:
            raw = self._redis.lrange(self._key(conversation_id), 0, -1)
            out: list[ChatMessage] = []
            for item in raw:
                role, _, content = item.partition("|")
                out.append(ChatMessage(role=role, content=content))
            return out[-self.settings.memory_max_messages :]
        with self._lock:
            state = self._local.get(str(conversation_id))
            if not state:
                return []
            if time.time() - state.updated_at > self.settings.memory_ttl_seconds:
                self._local.pop(str(conversation_id), None)
                return []
            return list(state.messages)

    def append(self, conversation_id: UUID, role: str, content: str) -> None:
        if not content:
            return
        if self._redis is not None:
            key = self._key(conversation_id)
            self._redis.rpush(key, f"{role}|{content}")
            self._redis.ltrim(key, -self.settings.memory_max_messages, -1)
            self._redis.expire(key, self.settings.memory_ttl_seconds)
            return
        with self._lock:
            state = self._local.setdefault(str(conversation_id), ConversationState())
            state.messages.append(ChatMessage(role=role, content=content))
            while len(state.messages) > self.settings.memory_max_messages:
                state.messages.popleft()
            state.updated_at = time.time()


class RateLimiter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = Lock()
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._last: dict[str, float] = {}

    def check(self, user_id: UUID, device_id: UUID | None = None) -> None:
        key = f"{user_id}:{device_id or 'none'}"
        now = time.time() * 1000
        with self._lock:
            last = self._last.get(key, 0)
            if now - last < self.settings.rate_limit_min_interval_ms:
                raise RuntimeError("Please wait a moment before sending another question.")
            window_start = now - self.settings.rate_limit_window_ms
            stamps = [t for t in self._windows[key] if t >= window_start]
            if len(stamps) >= self.settings.rate_limit_count:
                raise RuntimeError("Chat request limit reached. Please retry later.")
            stamps.append(now)
            self._windows[key] = stamps
            self._last[key] = now
