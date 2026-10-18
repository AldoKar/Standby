![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Standby Caller — phones the places that have no API

**Calls a business, asks for what you need, and reports back what was agreed. $1.99 a call.**

Most of travel is bookable by API. The guesthouse whose front desk closes at 11 PM is not.
This agent phones it, says plainly that it is an AI, asks the human for what you need, and
returns the answer as structured data.

## How to use it

Tell it who to call and what to ask:

> Call the Hayes St Guesthouse and hold my room for a late arrival

It replies with the opening line it will use, sends a payment request for $1.99 over the
Agent Payment Protocol, and places the call once the payment is committed. You get back a
plain-English summary and a JSON outcome: whether it was held, the door code, who was
spoken to, and any fee they asked for.

It is also hired by the [Standby orchestrator](https://agentverse.ai) as part of rebooking
a cancelled flight.

## Rules it will not break

- It says it is an AI, and that the call is recorded, in its first sentence.
- Business lines only. It will not call a private individual.
- It never phones or pays the airline that cancelled your flight.
- It never speaks or hears card details.
- One retry if nobody answers, then it tells you rather than pretending.

## Paying for it

$1.99 per call, charged through the Agent Payment Protocol — the caller is the seller,
you are the buyer. The protocol handshake is real; settlement is simulated for the
hackathon, since these agents hold no funds.
