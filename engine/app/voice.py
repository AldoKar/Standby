"""Voice commands from the glasses: audio -> text -> one intent from a closed list.

1. Speech to text: OpenRouter /audio/transcriptions (Whisper large v3 turbo by default).
2. Intent: a keyword fast path for short answers ("yes", "no", "another one"); if that misses, the
   primary model (Jev, a decision model, ~0.2 s) picks one intent from the ones the current screen allows;
   if Jev fails, times out or isn't sure, the fallback chat model (Claude Haiku) answers instead.

The voice layer never decides on money. An "approve" on a spend screen comes back with
confirm_required, and the glasses ask for a tap; the spend still goes through policy.py.
English only for now.

Env: OPENROUTER_API_KEY, VOICE_STT_MODEL, VOICE_INTENT_MODEL, VOICE_FALLBACK_MODEL (see engine/.env.example).
"""
from __future__ import annotations

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1"
STT_MODEL = os.getenv("VOICE_STT_MODEL", "openai/whisper-large-v3-turbo")
# Primary intent model. A decision model (Jev, ~0.2 s) goes through the Decisions API; a chat model through
# /chat/completions. The fallback answers only when the primary fails, times out or isn't sure.
INTENT_MODEL = os.getenv("VOICE_INTENT_MODEL", "typesafe/jev-1.14")
FALLBACK_MODEL = os.getenv("VOICE_FALLBACK_MODEL", "meta-llama/llama-3.3-70b-instruct")
STT_TIMEOUT_S = 8.0
DECISIONS_TIMEOUT_S = 2.5  # Jev's p95 is ~0.3 s; past this, the fallback is faster than waiting
CHAT_TIMEOUT_S = 5.0
# Decision models other than Jev share the same API (contract: OpenRouter "Other decision models").
DECISION_HINTS = ("-decisions", "-decide", "decision-", "pplx-decider", "/clef", "liquid/d1")
MIN_CONFIDENCE = 0.7
MAX_AUDIO_BYTES = 1_500_000  # ~45 s of 16 kHz mono WAV; voice commands are a few seconds

# Intents each screen accepts, and the gesture each one becomes. Anything else is "unknown".
INTENTS: dict[str, dict[str, str]] = {
    "cancelled": {"fix": "press"},
    "booking_offer": {"approve": "hold", "other_option": "swipe_down"},
    "only_option": {"approve": "hold"},
    "fee_request": {"approve": "hold", "reject": "swipe_down"},
    "claim_ready": {"approve": "press", "reject": "swipe_down"},  # submit the trip claim, or keep it for later
}

# Intents that approve a spend: never applied by voice, the wearer confirms with a tap.
SPEND_APPROVALS = {("booking_offer", "approve"), ("only_option", "approve"), ("fee_request", "approve")}

# Written as a spec, not a hint: decision models like Jev read criteria literally.
DESCRIPTIONS = {
    "fix": "The traveler wants Standby to go ahead and fix the cancelled trip "
           "(for example: yes, fix it, sort it out, handle it, go ahead).",
    "approve": "The traveler agrees to or accepts exactly what the glasses show "
               "(for example: yes, book it, OK, that works, pay it, sounds good).",
    "reject": "The traveler declines what the glasses show "
              "(for example: no, don't, that's too much, tell them no, not that).",
    "other_option": "The traveler asks for a different option instead of the one shown "
                    "(for example: another flight, other trips, something else, what else is there).",
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


class IntentError(Exception):
    """A model couldn't answer (HTTP error, timeout, unparseable). Never shown as "didn't understand"."""


UNKNOWN_CRITERION = "Anything else: unrelated talk, a question, unclear, or mixed signals."


def is_decisions_model(model: str) -> bool:
    """Decision ("System One") models live on /api/alpha/decisions, not /chat/completions."""
    m = model.lower()
    return m.startswith(("typesafe/", "~typesafe/")) or any(k in m for k in DECISION_HINTS)


async def _decisions_intent(model: str, transcript: str, lines: list[str], allowed: dict[str, str]) -> tuple[str, float]:
    """One Choice question on the Decisions API (Jev and other decision models)."""
    criteria = {i: DESCRIPTIONS[i] for i in allowed} | {"unknown": UNKNOWN_CRITERION}
    body = {
        "model": model,
        "state": {"traveler_said": transcript, "glasses_show": " / ".join(lines)},
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "What does the traveler want, given what the glasses show?",
                "criteria": criteria,
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=DECISIONS_TIMEOUT_S) as client:
            r = await client.post(f"{OPENROUTER_URL.replace('/v1', '/alpha')}/decisions",
                                  headers={"Authorization": f"Bearer {_key()}"}, json=body)
    except httpx.HTTPError as e:
        raise IntentError(f"{model}: {type(e).__name__}") from e
    if r.is_error:
        raise IntentError(f"{model}: HTTP {r.status_code} {r.text[:160]}")
    try:
        answer = r.json()["answers"]["intent"]
        choice, confidence = answer["choice"], float(answer.get("confidence", 0))
    except (ValueError, KeyError, TypeError) as e:
        raise IntentError(f"{model}: unexpected response {r.text[:160]}") from e
    if choice not in criteria:
        raise IntentError(f"{model}: answered {choice!r}, not one of the options")
    return choice, confidence


async def _chat_intent(model: str, transcript: str, lines: list[str], allowed: dict[str, str]) -> tuple[str, float]:
    """Chat model with a strict JSON schema whose intent is an enum of the allowed options."""
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
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT_S) as client:
            r = await client.post(
                f"{OPENROUTER_URL}/chat/completions",
                headers={"Authorization": f"Bearer {_key()}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 40,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": transcript}],
                    "response_format": {"type": "json_schema",
                                        "json_schema": {"name": "intent", "strict": True, "schema": schema}},
                },
            )
    except httpx.HTTPError as e:
        raise IntentError(f"{model}: {type(e).__name__}") from e
    if r.is_error:
        raise IntentError(f"{model}: HTTP {r.status_code} {r.text[:160]}")
    try:
        content = r.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", content, re.S)  # tolerate models that wrap JSON in prose
        data = json.loads(match.group(0) if match else content)
        intent, confidence = data["intent"], float(data.get("confidence", 0))
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise IntentError(f"{model}: unexpected response") from e
    if intent not in options:
        raise IntentError(f"{model}: answered {intent!r}, not one of the options")
    return intent, confidence


async def _ask(model: str, transcript: str, lines: list[str], allowed: dict[str, str]) -> tuple[str, float]:
    if is_decisions_model(model):
        return await _decisions_intent(model, transcript, lines, allowed)
    return await _chat_intent(model, transcript, lines, allowed)


async def _model_intent(transcript: str, lines: list[str], allowed: dict[str, str]) -> tuple[str, float, str, str | None]:
    """Primary model first (fast, e.g. Jev); the fallback (Haiku) only when the primary fails or isn't sure.

    Returns (intent, confidence, model_used, error). A confident "unknown" from the primary is accepted:
    re-asking a slower model about unrelated talk only adds latency.
    """
    if not _key():
        return "unknown", 0.0, "none", "voice not configured: no OPENROUTER_API_KEY"
    errors: list[str] = []
    models = [INTENT_MODEL] + ([FALLBACK_MODEL] if FALLBACK_MODEL and FALLBACK_MODEL != INTENT_MODEL else [])
    best: tuple[str, float, str] | None = None
    for i, model in enumerate(models):
        last = i == len(models) - 1
        try:
            intent, confidence = await _ask(model, transcript, lines, allowed)
        except IntentError as e:
            errors.append(str(e))
            continue
        if confidence >= MIN_CONFIDENCE or last:
            best = (intent, confidence, model)
            break
        best = (intent, confidence, model)  # not sure: keep it, but let the fallback have a go
        errors.append(f"{model}: low confidence {confidence:.2f} for {intent}")
    if best is None:
        return "unknown", 0.0, models[-1], "intent model failed: " + " | ".join(errors)
    intent, confidence, used = best
    if confidence < MIN_CONFIDENCE:
        intent = "unknown"
    return intent, confidence, used, ("; ".join(errors) or None)


async def classify(transcript: str, screen_id: str, lines: list[str]) -> tuple[str, float, str, str | None, str | None]:
    """Return (intent, confidence, via, model, note).

    via is "keywords", "model" or "none"; model is the one that answered; note explains a failure or a
    fallback (e.g. "typesafe/jev-1.14: HTTP 400 ..."), so errors are never reported as "didn't understand".
    """
    allowed = intents_for(screen_id)
    if not transcript or not allowed:
        return "unknown", 0.0, "none", None, None
    fast = _fast_intent(transcript, allowed)
    if fast:
        return fast, 1.0, "keywords", None, None
    intent, confidence, used, note = await _model_intent(transcript, lines, allowed)
    return intent, confidence, "model", used, note
