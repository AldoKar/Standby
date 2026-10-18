"""Real outbound call through ElevenLabs Agents on a Twilio number (owner: P4).

Used when CALL_MODE=elevenlabs. Check the request against the current
ElevenLabs docs ("Twilio outbound call") before relying on it.
"""
import os

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
        r.raise_for_status()
        return r.json()
