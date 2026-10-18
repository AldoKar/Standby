![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Standby — travel disruption orchestrator

**Rebooks cancelled flights within a spending mandate, then phones places with no API.**

When your flight is cancelled, Standby finds a seat that still gets you there tonight,
asks you once before it spends, books it, and then calls the places that only answer a
phone — the guesthouse whose front desk closes before you land.

## What it does

1. Loads the cancelled booking and ranks the alternatives against your spending mandate.
   Options that miss the deadline or break the budget are struck through with the reason.
2. Shows a review card: flight, price, what is left of the budget, and a fee allowance.
3. On approval, books the seat, declines the airline's own rebooking (so the refund is
   automatic) and saves the boarding pass.
4. Spots the downstream problem — the front desk closes at 11 PM, you land at 10:40 —
   and has the Caller agent phone the guesthouse to hold the room.
5. Reports the outcome: room held, door code, and the mandate ledger.

The whole flow runs inside one ASI:One chat. Type `status?` at any point for the current
state of the task.

## Guardrails

- Every spending decision is made in code by the engine's policy module, never by the LLM.
- The LLM never sees card data. It phrases replies and picks tools; the engine decides
  money and approvals.
- Calls go to business lines only, and the caller says it is an AI in its first sentence.

## Try it

> My UA183 got cancelled, handle it
