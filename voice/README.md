# Voice agent: ElevenLabs + Twilio (owner: P4)

The agent phones the guesthouse, which has no API, says it is an AI in its first sentence, and pauses to get the wearer's OK before agreeing to any extra cost.

## Setup

Step by step in [`setup.md`](setup.md). In short:

1. In ElevenLabs, create an Agent with the prompt and first message below.
2. Buy or import a Twilio number into ElevenLabs (native Twilio integration). Upgrade the Twilio account ($20) so callees don't hear the trial message.
3. Add the two server tools from `tools.json`, pointing at the engine's public URL.
4. Set `CALL_MODE=elevenlabs` plus the ElevenLabs variables in `engine/.env`. The engine places the call itself after booking, using `engine/app/call.py` (checked against the ElevenLabs docs on Oct 17; see [`NEEDS-FROM-P1.md`](NEEDS-FROM-P1.md)).
5. Post-call: point ElevenLabs' post-call webhook at `https://<engine>/call/webhook` and add the data collection fields `held`, `door_code`, `contact`, `fee_usd`. The engine checks them against the transcript with Claude and only then shows the door code.

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
  then call check_approval with the approval_id until the status is not "pending", at most 4 times.
  Each check waits several seconds. If a check comes back pending, say one short line such as
  "Still checking with him, thanks for waiting" before the next check.
  - approved: agree and continue.
  - rejected or denied: politely decline the fee and ask whether the room can still be held.
  - still pending after 4 checks: say you will call back, and end the call.
- The line may be noisy. If what you hear is unclear, very short or sounds like background chatter,
  don't apologize or restart your introduction; ask once, briefly, "Sorry, could you say that again?"
  and continue.
- Say confirmation numbers and door codes digit by digit, for example "4-8-2-1-3".
- Keep it short: at most 3 exchanges with the clerk.
- Before hanging up, repeat back what was agreed: room held or not, fee, door code, contact name.
  Then end the call.
```

## Fallbacks

- No ring within 10 seconds → the dashboard plays a recorded real call.
- The approval loop is flaky → keep the agent talking with a filler line; last resort, ask "Fees up to $30 OK?" before the call.

## Checklist

- [ ] 7:00 PM: a real call rings P4's phone with the disclosure line
- [ ] 8:00 PM: mid-call approval passes 5 of 5 on a real call, with the clerk waiting about 20 seconds
- [ ] 2:00 AM: 2 recorded real calls saved for the fallback
