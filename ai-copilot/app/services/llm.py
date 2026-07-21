from __future__ import annotations

from openai import AsyncOpenAI

from app.config import Settings


class LlmService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key or "missing", timeout=settings.openai_timeout_seconds)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.settings.openai_api_key:
            return (
                "AI model is not configured on the copilot service. "
                "Live telemetry/alarms context was gathered, but no LLM key is set."
            )
        resp = await self._client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
