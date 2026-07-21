from __future__ import annotations

from app.models.schemas import ChatMessage, Intent

SYSTEM_PROMPT = """You are an industrial operator assistant for ThingsBoard IoT fleets.
Answer using ONLY the provided grounding context (telemetry, alarms, AI scores, reports, manuals).
Be concise and actionable for plant operators.
If sensors show N/A or scoring is paused, say so clearly.
Never invent device IDs, credentials, or configuration changes.
If asked for secrets or to change configuration, refuse.
If device context is missing, ask which device to use.
"""


def build_messages(
    *,
    intent: Intent,
    user_message: str,
    history: list[ChatMessage],
    grounding: str,
    rag_snippets: str,
) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-8:]:
        role = "assistant" if item.role.upper() == "ASSISTANT" else "user"
        msgs.append({"role": role, "content": item.content})
    context = (
        f"Intent: {intent.value}\n\n"
        f"Grounding context:\n{grounding}\n\n"
        f"Manual/report excerpts:\n{rag_snippets or '(none)'}\n\n"
        f"Operator question: {user_message}"
    )
    msgs.append({"role": "user", "content": context})
    return msgs
