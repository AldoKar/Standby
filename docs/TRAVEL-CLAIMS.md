# Travel-benefit claims: how they work today, and what the demo simulates

Research notes for the trip claim feature (`engine/app/claims.py`, the `claim` agent phase) and for the Visa track pitch. Checked on 2026-10-18.

## What Handle It does

After the trip is handled, Claude reads the traveler's travel benefits (Vault) and every payment (ledger), and drafts one claim that cites each receipt. `claims.py` checks every amount, the same way `policy.py` checks spends: trip interruption pays the new fare minus the airline refund, trip delay pays fees caused by the cancellation, caps apply, and a wrong item refuses the whole claim so Claude fixes it. Nothing is sent until the wearer taps "submit".

In the demo: $215 Delta fare - $189 United refund = $26, plus the $40 late check-in fee, so the claim is $66 and the cancellation costs the traveler $0 extra.

## Real vs simulated

| Part | Status |
|---|---|
| Claude reading benefits and receipts, deciding and writing the letter | Real (Claude Opus 5.5 with tools) |
| Code checking each amount, caps, duplicates, merchant categories | Real (`claims.py`) |
| Receipts | Each item carries a copy of the payment from the ledger: merchant, amount, category, time, signing key id and whether the TAP-style signature verified. No files are attached |
| Benefit terms (trip interruption $1,500, trip delay $500) | Demo data, labeled simulated. Real terms vary by card and issuer |
| Submitting the claim | Simulated: the tap marks it submitted. Nothing is sent anywhere |
| Getting paid | Simulated: "$66 expected back" is what a real claim should pay |

## How card travel claims work today (Visa, U.S.)

- Claims are handled by a third-party **Benefit Administrator** (for U.S. Visa benefits, *Card Benefit Services*, Richmond, VA), not by Visa itself.
- The process is manual: call the Benefit Administrator **within 30 days** of the delay, get a claim form, then send the signed form and documents **within 90 days**, by mail. Missing either deadline can deny the claim.
- Some regions use the **Visa Benefits Portal** (`visa.com/benefitsportal`): log in, create a claim, upload documents.
- Documents usually required: the card receipt showing the full fare was charged to the card, a copy of the ticket, **a statement from the carrier explaining the delay or cancellation**, and receipts for the claimed expenses.
- Example of real terms (Preferred Visa Signature, trip delay): the trip must be delayed **more than 12 hours** by a covered hazard (equipment failure, weather, strike, hijacking), it pays **up to $300 per ticket** for reasonable meals and lodging, and it is **supplemental** (only what the carrier or other insurance doesn't cover). Visa Infinite cards often have shorter delays and higher limits.

## Is there an API?

- **Visa:** we found no public API for filing or tracking benefit claims.
- **Mastercard:** Mastercard Loyalty Insurance has issuer-side APIs, with sandbox and production. The issuer's back end can show a cardholder's benefits and check a claim's status (`GET /claim-searches`); filing a claim redirects the cardholder to the benefits provider's page. It is for issuers, not third-party developers.
- **Allianz Partners** (underwrites embedded card benefits for banks) doesn't publish an API.

So "submit to the issuer's claims API" is a proposal, not something that exists today for Visa.

## What to say in the pitch

> Today, claiming card travel benefits means a phone call within 30 days, a paper form and mailing receipts within 90 days, so most people never claim. Handle It prepares the whole claim automatically, with the receipts and the reason, and you approve it with one tap. Submission is simulated: Visa has no public claims API today. Mastercard already exposes claim status to issuers, which shows where the industry is going.

If a judge asks about the terms: they're demo values; real ones vary, for example Preferred Visa Signature needs a 12-hour delay and pays up to $300.

## Possible next steps

- Say "receipts referenced" instead of "attached" in the claim letter (no files are attached).
- Add to the claim the documents the administrator asks for that we already have: the cancellation notice and the new ticket (PNR).
- Track the 30-day and 90-day deadlines in the Vault.

## Sources

- [Preferred Visa Signature trip delay terms (UBS)](https://www.ubs.com/microsites/wma/insights/en/rewards/preferre-t-c-trip-delay.html)
- [Visa Infinite trip delay](https://eu.review.visa.com/content/dam/VCOM/regional/na/us/pay-with-visa/documents/trip-delay-infinite.pdf)
- [Visa trip delay, Caribbean](https://caribbean.review.visa.com/content/dam/VCOM/regional/lac/ENG/benefits/trip-delay-eng-01.pdf)
- [Mastercard Loyalty Insurance documentation](https://developer.mastercard.com/mastercard-insurance-programs/documentation/)
- [Mastercard Loyalty Insurance use cases](https://developer.mastercard.com/mastercard-insurance-programs/documentation/use-cases/)
- [Allianz Partners bankcard services](https://www.allianzworldwidepartners.com/usa/bankcard-services)
