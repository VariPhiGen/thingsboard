from __future__ import annotations

import re

from openai import AsyncOpenAI

from app.config import Settings

_BANNED_TERMS = (
    (re.compile(r"\bThingsBoard\b", re.I), "the dashboard"),
    (re.compile(r"\bTB\b"), "the dashboard"),
    (re.compile(r"\bIoT platform\b", re.I), "plant monitoring system"),
    (re.compile(r"\btelemetry\b", re.I), "live readings"),
    (re.compile(r"\bAPI\b"), "system"),
)


def soften_operator_language(text: str) -> str:
    out = text or ""
    for pattern, replacement in _BANNED_TERMS:
        out = pattern.sub(replacement, out)
    return out


class LlmService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key or "missing", timeout=settings.openai_timeout_seconds)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.settings.openai_api_key:
            return (
                "The assistant model is not configured yet. "
                "Live readings and alarms were checked where possible, but I cannot generate a full answer until the model key is set."
            )
        resp = await self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            temperature=0.2,
        )
        return soften_operator_language((resp.choices[0].message.content or "").strip())
