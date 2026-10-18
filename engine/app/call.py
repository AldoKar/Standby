"""Real outbound call through ElevenLabs Agents on a Twilio number (owner: P4).

Used when CALL_MODE=elevenlabs. Check the request against the current
ElevenLabs docs ("Twilio outbound call") before relying on it.
"""
import hashlib
import hmac
import os
import time

import httpx

OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"


async def start_call(dynamic_variables: dict) -> dict:
    payload = {
        "agent_id": os.environ["ELEVENLABS_AGENT_ID"],
        "agent_phone_number_id": os.environ["ELEVENLABS_PHONE_NUMBER_ID"],
        "to_number": os.environ["CALL_TO_NUMBER"],
        "conversation_initiation_client_data": {"dynamic_variables": dynamic_variables},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(OUTBOUND_URL, headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, json=payload)
    if r.is_error:  # keep ElevenLabs' error body so the dashboard can say why
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success"):  # a 200 with success: false means no call was placed
        raise RuntimeError(f"ElevenLabs did not place the call: {body.get('message')}")
    return body  # success, message, conversation_id, callSid


# ---------- post-call webhook ----------

WEBHOOK_TOLERANCE_S = 30 * 60  # same window as the ElevenLabs SDK


def signature_ok(raw_body: bytes, header: str | None, secret: str | None) -> bool:
    """Check the `ElevenLabs-Signature: t=<unix>,v0=<hex hmac>` header.
    Same scheme as the SDK's webhooks.construct_event: HMAC-SHA256 of "<t>.<body>"."""
    if not header or not secret:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, sig = parts.get("t", ""), parts.get("v0", "")
    if not t.isdigit() or int(t) < time.time() - WEBHOOK_TOLERANCE_S:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def transcript_text(turns: list[dict]) -> str:
    """ElevenLabs transcript turns -> "Agent: ...\nClerk: ..." for verify.check_call."""
    who = {"agent": "Agent", "user": "Clerk"}
    return "\n".join(f"{who.get(t.get('role'), t.get('role'))}: {t['message']}" for t in turns if t.get("message"))


def reported_outcome(data: dict) -> dict:
    """What the voice agent's data collection says, if P4 configured it (held, door_code, contact, fee_usd)."""
    results = (data.get("analysis") or {}).get("data_collection_results") or {}
    out = {k: (results.get(k) or {}).get("value") for k in ("held", "door_code", "contact", "fee_usd")}
    out["held"] = out["held"] in (True, "true", "True", "yes")
    return out
