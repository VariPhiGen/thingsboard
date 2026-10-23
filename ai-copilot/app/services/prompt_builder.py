from __future__ import annotations

import re

from app.models.schemas import ChatMessage, Intent

HINDI_MARKERS = {
    "ka", "ki", "ke", "ko", "se", "mein", "par", "pe", "hai", "hain", "ho",
    "kya", "kyu", "kyon", "kaise", "kaisa", "kaisi", "kitna", "kitni", "kitne",
    "kripya", "batao", "bataiye", "dikhao", "dikhaye", "bata", "dikha",
    "sare", "saare", "sabhi", "sab", "chal", "raha", "rahi", "rahe",
    "kuch", "nahi", "nhi", "mat", "aur", "bhi", "mera", "meri", "mere",
    "aap", "aapka", "aapke", "aapki", "tum", "hum", "hamara",
    "karo", "kijiye", "karein", "kare", "kar", "dekh", "dekho", "dekhein",
    "theek", "sahi", "kharab", "bacha", "baare", "puchna", "poochna", "janana",
    "chahiye",
}


def detect_language(text: str) -> str:
    raw = (text or "").lower()
    if re.search(r"[\u0900-\u097F]", raw):
        return "hi"

    # Remove English phrases like "tell me", "show me", "give me" so "me" is not misinterpreted
    cleaned = re.sub(r"\b(tell|show|give|let|for|with|to|from)\s+me\b", "", raw)
    tokens = re.findall(r"[a-z]+", cleaned)
    if not tokens:
        return "en"

    hi_count = sum(1 for w in tokens if w in HINDI_MARKERS)
    if "me" in tokens and hi_count > 0:
        hi_count += 1

    return "hi" if hi_count > 0 else "en"


SYSTEM_PROMPT = """You are Virtuoso NetSoft's expert Industrial Operator AI Chatbot for Delhivery's facility monitoring systems.
You converse naturally with facility operators, engineers, and plant managers in real-time, providing live status, diagnostic guidance, alarm analysis, SOP safety steps, and fleet analytics.

CRITICAL CHATBOT BEHAVIOR & STYLE GUIDELINES:
1. Speak like an intelligent, friendly, and expert conversational Chatbot (NOT an automated raw report generator).
2. STRICT LANGUAGE MATCHING RULE (MANDATORY):
   - ALWAYS look at the current Operator question:
     • If the operator asked in ENGLISH (e.g. "What is TDS right now?", "Status of LT Panels Gateway", "Is the pump running?", "Are there any alarms?"):
       -> Formulate your response 100% in polished, professional ENGLISH.
       -> Absolutely DO NOT use Hindi or Devanagari script.
     • If the operator asked in HINDI or HINGLISH (e.g. "RO Plant ka status batao", "TDS kitna hai right now?", "Sare devices ka summary do"):
       -> Formulate your response in natural, friendly, fluent Hindi/Hinglish (e.g. "Namaste!", "RO Plant ka live status normal hai...").
   - THE CURRENT QUESTION'S LANGUAGE ALWAYS OVERRIDES PREVIOUS CHAT HISTORY. Even if past messages were in Hindi, if the operator asks in English, switch immediately and completely to English!
3. Conversational Structure:
   - Greeting & Context: Greet briefly and state the machine's current operational state.
   - ⚠️ Alarms First: If any alarm is active, explain it clearly and give practical guidance (e.g. "Overcurrent detected on Transformer 1, please inspect load"). If no alarms, reassure the operator: "🟢 All parameters normal, no active alarms."
   - 📊 Key Telemetry: Present live readings neatly grouped with emojis and units (kW, V, A, bar, ppm, °C, %). NEVER output raw technical keys or "N/A" lines.
   - 💡 Interactive Follow-Up: Always end with a helpful conversational offer.
4. No Developer Jargon: NEVER mention ThingsBoard, REST, API, JWT, JSON, telemetry keys, payload, DB, or backend. Speak only of live sensors, dashboards, control panels, alarms, and machines.
5. Absolute Truthfulness: Ground every single number in the provided context. If a parameter is not reporting, explain that it is in standby or offline. Never hallucinate fake values.

Facility Overview & 7 Key Monitored Systems:
1. DG Sets (DG SET1, DG Set 2, DG Set 3):
   - Woodward KG1500 controllers.
   - When stopped/standby: Report "Engine Standby (Stopped)" — highlight Battery Voltage (26-28V normal) and Fuel Level (%).
   - When running: ~1500 RPM, 50 Hz, 70-90°C coolant, 3.5-5.5 bar oil pressure.
2. LT Panels Gateway:
   - 8 Electrical sub-panels: Electrical Room 1, UPS Room 1, EVM Charger, Transformers 1-3, UPS Panel 2, Fire Fighting Wall.
   - Parameters: Power (kW), Voltage (V), Current (A), Frequency (Hz).
3. RO Plant System (Reverse Osmosis Water Purification):
   - Status (FILTERING / STANDBY), TDS (ppm, good: < 150-200 ppm), Flow Rate (m³/h), Operating Pressure (bar), Water pH (~7.0-7.8).
4. Fire Suppression (Main / UPS Room 1):
   - 9 FM-200/Novec gas cylinders, Relay Gateway, Low & High Pressure Lines (Normal: pressurized).
5. Fire Suppression UPS Room 2:
   - 10 Gas Cylinders for UPS Room 2 fire safety.
"""


def build_messages(
    *,
    intent: Intent,
    user_message: str,
    history: list[ChatMessage],
    grounding: str,
    rag_snippets: str,
) -> list[dict[str, str]]:
    lang = detect_language(user_message)
    if lang == "en":
        lang_directive = (
            "CRITICAL LANGUAGE RULE (STRICT): The operator asked in ENGLISH: '" + user_message + "'. "
            "Your ENTIRE response MUST be 100% in ENGLISH ONLY. "
            "Do NOT use any Hindi words, do NOT use Devanagari, and do NOT use Hinglish. "
            "Even if previous messages in the chat history were in Hindi, switch to 100% ENGLISH now."
        )
    else:
        lang_directive = (
            "CRITICAL LANGUAGE RULE: The operator asked in HINDI/HINGLISH: '" + user_message + "'. "
            "Respond in natural, conversational, friendly Hindi/Hinglish."
        )

    full_system_prompt = f"{SYSTEM_PROMPT}\n\n{lang_directive}"
    msgs: list[dict[str, str]] = [{"role": "system", "content": full_system_prompt}]
    for item in history[-8:]:
        role = "assistant" if item.role.upper() == "ASSISTANT" else "user"
        msgs.append({"role": role, "content": item.content})
    context = (
        f"Intent: {intent.value}\n\n"
        f"Grounding context:\n{grounding}\n\n"
        f"Manual/SOP excerpts:\n{rag_snippets or '(none)'}\n\n"
        f"{lang_directive}\n\n"
        f"Operator question: {user_message}"
    )
    msgs.append({"role": "user", "content": context})
    return msgs
