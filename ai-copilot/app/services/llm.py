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
        openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        gemini_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")

        # Prefer active OpenAI key if present
        if openai_key and openai_key.startswith("sk-"):
            api_key = openai_key
            base_url = "https://api.openai.com/v1"
            model = settings.openai_model if settings.openai_model and not settings.openai_model.startswith("gemini") else "gpt-4o-mini"
        elif gemini_key or (openai_key and (openai_key.startswith("AQ.") or openai_key.startswith("AIza"))):
            api_key = gemini_key or openai_key
            base_url = settings.openai_base_url or os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
            model = settings.openai_model if settings.openai_model and settings.openai_model.startswith("gemini") else "gemini-2.5-flash"
        else:
            api_key = openai_key or gemini_key
            base_url = settings.openai_base_url or os.getenv("OPENAI_BASE_URL", "")
            model = settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

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
