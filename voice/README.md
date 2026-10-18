# Voice agent: ElevenLabs + Twilio (owner: P4)

The agent phones the guesthouse, which has no API, says it is an AI in its first sentence, and pauses to get the wearer's OK before agreeing to any extra cost.

## Setup

1. In ElevenLabs, create an Agent with the prompt and first message below.
2. Buy or import a Twilio number into ElevenLabs (native Twilio integration). Upgrade the Twilio account ($20) so callees don't hear the trial message.
3. Add the two server tools from `tools.json`, pointing at the engine's public URL.
4. Set `CALL_MODE=elevenlabs` plus the ElevenLabs variables in `engine/.env`. The engine places the call itself after booking, using `engine/app/call.py`; check that request against the current ElevenLabs docs.
5. Post-call: map ElevenLabs' post-call webhook (or a final tool call) to `POST /call/completed` with `{held, door_code, contact, fee_usd, transcript_url, verified}`.

## Dynamic variables

`guest_name`, `confirmation`, `eta`, `task_id`. The engine passes them when it starts the call.

## First message

> Hi, I'm an AI assistant calling for {{guest_name}}, confirmation {{confirmation}}; this call is recorded. His flight was cancelled and he'll arrive around {{eta}}. Can you hold the room and tell me how he gets in?

## System prompt

```
You are an AI assistant phoning a small guesthouse for a guest whose flight was cancelled.
Goal: keep the room for a late arrival and learn how the guest gets in (door code, contact name).

Rules:
- You already said you are an AI and that the call is recorded. Never pretend to be human.
- Never give, ask for or repeat card numbers. If asked for a card, say payment comes through
  a secure link and continue.
- Any extra cost, fee or change you did not already have approval for: say
  "One moment, let me check with him", call request_approval with the amount and reason,
  then call check_approval every 3 seconds until the status is not "pending", for up to 30 seconds.
  - approved: agree and continue.
  - rejected or denied: politely decline the fee and ask whether the room can still be held.
  - still pending after 30 seconds: say you will call back, and end the call.
- Keep it short: at most 3 exchanges with the clerk.
- Before hanging up, repeat back what was agreed: room held or not, fee, door code, contact name.
```

## Fallbacks

- No ring within 10 seconds → the dashboard plays a recorded real call.
- The approval loop is flaky → keep the agent talking with a filler line; last resort, ask "Fees up to $30 OK?" before the call.

## Checklist

- [ ] 7:00 PM: a real call rings P4's phone with the disclosure line
- [ ] 8:00 PM: mid-call approval passes 5 of 5 on a real call, with the clerk waiting about 20 seconds
- [ ] 2:00 AM: 2 recorded real calls saved for the fallback
