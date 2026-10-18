"""Voice commands from the glasses: audio -> text -> one intent from a closed list.

1. Speech to text: OpenRouter /audio/transcriptions (Whisper large v3 turbo by default).
2. Intent: a keyword fast path for short answers ("yes", "no", "another one"), then, only if that
   misses, an OpenRouter chat model that must pick one intent from the ones the current screen allows.

The voice layer never decides on money. An "approve" on a spend screen comes back with
confirm_required, and the glasses ask for a tap; the spend still goes through policy.py.
English only for now.

Env: OPENROUTER_API_KEY, VOICE_STT_MODEL, VOICE_INTENT_MODEL (see engine/.env.example).
"""
from __future__ import annotations

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1"
STT_MODEL = os.getenv("VOICE_STT_MODEL", "openai/whisper-large-v3-turbo")
INTENT_MODEL = os.getenv("VOICE_INTENT_MODEL", "anthropic/claude-haiku-4.5")
STT_TIMEOUT_S = 8.0
INTENT_TIMEOUT_S = 5.0
MIN_CONFIDENCE = 0.7
MAX_AUDIO_BYTES = 1_500_000  # ~45 s of 16 kHz mono WAV; voice commands are a few seconds

# Intents each screen accepts, and the gesture each one becomes. Anything else is "unknown".
INTENTS: dict[str, dict[str, str]] = {
    "cancelled": {"fix": "press"},
    "booking_offer": {"approve": "hold", "other_option": "swipe_down"},
    "only_option": {"approve": "hold"},
    "fee_request": {"approve": "hold", "reject": "swipe_down"},
}

# Intents that approve a spend: never applied by voice, the wearer confirms with a tap.
SPEND_APPROVALS = {("booking_offer", "approve"), ("only_option", "approve"), ("fee_request", "approve")}

DESCRIPTIONS = {
    "fix": "the traveler wants Standby to fix the cancelled flight / go ahead",
    "approve": "the traveler agrees / says yes / wants to book or accept what is on screen",
    "reject": "the traveler declines / says no to what is on screen",
    "other_option": "the traveler wants a different option / another flight / other trips",
}

# Keyword fast path: short utterances only, so "no, I mean yes" goes to the model.
YES = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "approve", "accept", "book", "confirm", "go", "do it",
       "go ahead", "sounds good", "fine", "fix it", "fix", "handle it", "please do", "yes please", "alright"}
NO = {"no", "nope", "nah", "decline", "reject", "dont", "don't", "no thanks", "not now", "skip", "pass"}
OTHER = {"other", "another", "different", "next", "else", "options", "alternatives", "something else"}
FAST_MAX_WORDS = 4


def intents_for(screen_id: str) -> dict[str, str]:
    return INTENTS.get(screen_id, {})


def needs_tap(screen_id: str, intent: str) -> bool:
    return (screen_id, intent) in SPEND_APPROVALS


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).strip()


def _fast_intent(transcript: str, allowed: dict[str, str]) -> str | None:
    words = _normalize(transcript).split()
    if not words or len(words) > FAST_MAX_WORDS:
        return None
    phrase = " ".join(words)
    grams = set(words) | {" ".join(words[i:i + 2]) for i in range(len(words) - 1)} | {phrase}
    yes, no, other = bool(grams & YES), bool(grams & NO), bool(grams & OTHER)
    if sum((yes, no, other)) != 1:
        return None  # nothing matched, or mixed signals ("no, yes"): let the model decide
    if other:
        return "other_option" if "other_option" in allowed else None
    if yes:
        return next((i for i in ("approve", "fix") if i in allowed), None)
    # "no": a reject where the screen has one; on the booking offer a "no" means "show me another"
    return next((i for i in ("reject", "other_option") if i in allowed), None)


def _key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or None


async def transcribe(audio_b64: str, fmt: str = "wav") -> str:
    """Speech to text through OpenRouter. Raises RuntimeError with a short reason."""
    key = _key()
    if not key:
        raise RuntimeError("voice not configured: no OPENROUTER_API_KEY")
    async with httpx.AsyncClient(timeout=STT_TIMEOUT_S) as client:
        r = await client.post(
            f"{OPENROUTER_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": STT_MODEL, "input_audio": {"data": audio_b64, "format": fmt}, "language": "en",
                  "temperature": 0},
        )
    if r.is_error:
        raise RuntimeError(f"transcription failed: HTTP {r.status_code} {r.text[:200]}")
    return (r.json().get("text") or "").strip()


async def _model_intent(transcript: str, screen_id: str, lines: list[str], allowed: dict[str, str]) -> tuple[str, float]:
    key = _key()
    if not key:
        return "unknown", 0.0
    options = list(allowed) + ["unknown"]
    system = (
        "You map what a traveler said to their smart glasses to exactly one intent.\n"
        f"The glasses show: {' / '.join(lines)}\n"
        "Allowed intents:\n"
        + "\n".join(f"- {i}: {DESCRIPTIONS[i]}" for i in allowed)
        + "\n- unknown: anything else, unrelated, unclear, or a question\n"
        'Reply with JSON only: {"intent": "<one allowed intent>", "confidence": <0..1>}'
    )
    schema = {
        "type": "object",
        "properties": {"intent": {"type": "string", "enum": options}, "confidence": {"type": "number"}},
        "required": ["intent", "confidence"],
        "additionalProperties": False,
    }
    try:
        async with httpx.AsyncClient(timeout=INTENT_TIMEOUT_S) as client:
            r = await client.post(
                f"{OPENROUTER_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": INTENT_MODEL,
                    "temperature": 0,
                    "max_tokens": 40,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": transcript}],
                    "response_format": {"type": "json_schema",
                                        "json_schema": {"name": "intent", "strict": True, "schema": schema}},
                },
            )
        if r.is_error:
            return "unknown", 0.0
        content = r.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", content, re.S)  # tolerate models that wrap JSON in prose
        data = json.loads(match.group(0) if match else content)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return "unknown", 0.0
    intent, confidence = data.get("intent"), data.get("confidence", 0)
    if intent not in allowed or not isinstance(confidence, (int, float)) or confidence < MIN_CONFIDENCE:
        return "unknown", float(confidence) if isinstance(confidence, (int, float)) else 0.0
    return intent, float(confidence)


async def classify(transcript: str, screen_id: str, lines: list[str]) -> tuple[str, float, str]:
    """Return (intent, confidence, via). via is "keywords", "model" or "none"."""
    allowed = intents_for(screen_id)
    if not transcript or not allowed:
        return "unknown", 0.0, "none"
    fast = _fast_intent(transcript, allowed)
    if fast:
        return fast, 1.0, "keywords"
    intent, confidence = await _model_intent(transcript, screen_id, lines, allowed)
    return intent, confidence, "model"
