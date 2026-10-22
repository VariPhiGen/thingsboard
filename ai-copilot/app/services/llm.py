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


import os
import logging

log = logging.getLogger(__name__)

class LlmService:
    def __init__(self, settings: Settings):
        self.settings = settings
        api_key = (
            settings.gemini_api_key
            or settings.openai_api_key
            or os.getenv("GEMINI_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
        )
        base_url = settings.openai_base_url or os.getenv("OPENAI_BASE_URL", "")
        model = settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        # Auto-detect Google Gemini authorization keys (starting with 'AQ.' or 'AIza')
        if api_key and (api_key.startswith("AQ.") or api_key.startswith("AIza")):
            if not base_url:
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            if model in ("gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo", ""):
                model = "gemini-2.5-flash"

        self.api_key = api_key
        self.base_url = base_url or None
        self.model = model

        client_kwargs = {
            "api_key": self.api_key or "missing",
            "timeout": settings.openai_timeout_seconds,
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self._client = AsyncOpenAI(**client_kwargs)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            return ""
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            return soften_operator_language((resp.choices[0].message.content or "").strip())
        except Exception as exc:
            log.warning("LLM completion failed (%s): %s", self.model, exc)
            raise
