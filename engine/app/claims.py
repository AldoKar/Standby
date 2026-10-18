"""Travel-benefit claims: what the traveler's benefits pay back after a disruption.

Claude reads the benefits and the receipts and drafts the claim; this file has the last word on
amounts, the same way policy.py does for spends. A claim item must cite a real payment, fit the
benefit's merchant categories and never exceed what the rules below allow:
- trip_interruption: the new fare minus what the carrier refunds for the original fare
  (the traveler would have paid that fare anyway, so only the difference is a loss);
- trip_delay: lodging/meal fees caused by the disruption, in full;
- each benefit has a cap per trip.
Benefits are demo data (contract/mock-data.json "travel_benefits"); real terms vary by issuer.

Self-check:  cd engine && python -m app.claims
"""
from __future__ import annotations

from .policy import Ledger, mcc_in


def max_claimable(spend: dict, benefit: dict, ledger: Ledger) -> tuple[float, str]:
    """The most this payment can claim under this benefit, and why."""
    if not mcc_in(benefit["mcc"], spend["mcc"]):
        return 0, f"{benefit['name']} doesn't cover merchant category {spend['mcc']}"
    if benefit["id"] == "trip_interruption":
        if spend["kind"] != "booking":
            return 0, "trip interruption covers the replacement flight only"
        refunded = sum(r["amount"] for r in ledger.refunds)
        # ponytail: one replacement flight per trip; split the refund across bookings if that changes
        extra = round(max(0.0, spend["amount"] - refunded), 2)
        return extra, f"new fare ${spend['amount']:g} minus the ${refunded:g} the carrier refunds"
    if benefit["id"] == "trip_delay":
        if spend["kind"] == "booking":
            return 0, "trip delay doesn't cover flights"
        return spend["amount"], f"${spend['amount']:g} {spend['merchant']} fee caused by the cancellation"
    return 0, f"unknown benefit {benefit['id']}"


def validate(items: list[dict], ledger: Ledger, program: dict) -> tuple[list[dict], list[str]]:
    """Check a drafted claim. Returns (items with evidence attached, problems); any problem rejects it all."""
    benefits = {b["id"]: b for b in program["benefits"]}
    spends = {s["reference"]: s for s in ledger.spends}
    problems, out, used, per_benefit = [], [], set(), {}
    for i in items:
        ref, bid, amount = i.get("reference"), i.get("benefit_id"), i.get("amount_usd")
        s, b = spends.get(ref), benefits.get(bid)
        if not s:
            problems.append(f"{ref}: no such payment")
            continue
        if not b:
            problems.append(f"{ref}: no benefit {bid}")
            continue
        if ref in used:
            problems.append(f"{ref}: claimed twice")
            continue
        top, why = max_claimable(s, b, ledger)
        if not isinstance(amount, (int, float)) or not amount > 0:
            problems.append(f"{ref}: amount must be positive")
        elif amount > top + 0.005:
            problems.append(f"{ref}: ${amount:g} is more than the ${top:g} allowed ({why})")
        else:
            used.add(ref)
            per_benefit[bid] = per_benefit.get(bid, 0) + amount
            out.append({"reference": ref, "benefit_id": bid, "benefit": b["name"], "amount_usd": round(amount, 2),
                        "reason": str(i.get("reason", ""))[:300], "rule": why,
                        "receipt": {"merchant": s["merchant"], "amount_usd": s["amount"], "mcc": s["mcc"],
                                    "paid_at": s["ts"], "signature_keyid": s["signature"]["keyid"],
                                    "signature_verified": s["signature"]["verified"]}})
    for bid, total in per_benefit.items():
        if total > benefits[bid]["cap_usd"]:
            problems.append(f"{benefits[bid]['name']}: ${total:g} is over the ${benefits[bid]['cap_usd']:g} cap")
    if not out and not problems:
        problems.append("nothing to claim")
    return out, problems


def draft(ledger: Ledger, program: dict) -> list[dict]:
    """The scripted claim (no Claude): each payment under its best benefit, at the allowed maximum."""
    items = []
    for s in ledger.spends:
        best = max(((max_claimable(s, b, ledger), b) for b in program["benefits"]), key=lambda x: x[0][0])
        (amount, why), b = best
        if amount > 0:
            items.append({"reference": s["reference"], "benefit_id": b["id"], "amount_usd": amount, "reason": why})
    return items


if __name__ == "__main__":
    import json
    from pathlib import Path
    program = json.loads((Path(__file__).resolve().parents[2] / "contract" / "mock-data.json").read_text())["travel_benefits"]
    sig = {"keyid": "k", "verified": True}
    ledger = Ledger(spends=[
        {"reference": "VIC-1", "kind": "booking", "amount": 215, "merchant": "Delta", "mcc": "3058", "ts": "t", "signature": sig},
        {"reference": "VIC-2", "kind": "fee", "amount": 40, "merchant": "Hayes St Guesthouse", "mcc": "7011", "ts": "t", "signature": sig}],
        refunds=[{"amount": 189}])
    items = draft(ledger, program)
    assert [(i["reference"], i["benefit_id"], i["amount_usd"]) for i in items] == [
        ("VIC-1", "trip_interruption", 26), ("VIC-2", "trip_delay", 40)], items
    assert validate(items, ledger, program)[1] == []
    assert "more than" in validate([{**items[0], "amount_usd": 215}], ledger, program)[1][0]  # full fare: refused
    assert "Trip delay doesn't cover" in validate([{**items[0], "benefit_id": "trip_delay"}], ledger, program)[1][0]
    assert "claimed twice" in validate([items[1], items[1]], ledger, program)[1][0]
    assert "no such payment" in validate([{**items[1], "reference": "VIC-9"}], ledger, program)[1][0]
    print("claims ok:", sum(i["amount_usd"] for i in items))
