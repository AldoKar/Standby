"""Real flight search and booking through Duffel (test mode: real API, no money moves).

FLIGHTS_MODE=duffel uses it; anything else (or any Duffel error) falls back to the mock
options in contract/mock-data.json, so the demo never breaks.

Try it (needs DUFFEL_TOKEN):  cd engine && python -m app.flights
"""
from __future__ import annotations

import asyncio
import os

import httpx

API = "https://api.duffel.com"
MAX_OPTIONS = 4
MCC_AIRLINE = "4511"  # airlines, inside the mandate's allowed MCCs
# Test-mode passenger; Duffel needs these fields to issue an order.
PASSENGER = {"title": "mr", "gender": "m", "given_name": "Alex", "family_name": "Rivera",
             "born_on": "1990-04-12", "email": "alex.rivera@example.com", "phone_number": "+14155552671"}


def enabled() -> bool:
    return os.getenv("FLIGHTS_MODE", "mock") == "duffel" and bool(os.getenv("DUFFEL_TOKEN"))


def test_mode() -> bool:
    return os.getenv("DUFFEL_TOKEN", "").startswith("duffel_test_")


async def _post(path: str, data: dict) -> dict:
    headers = {"Authorization": f"Bearer {os.environ['DUFFEL_TOKEN']}", "Duffel-Version": "v2",
               "Accept": "application/json", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=API, timeout=25) as c:
        r = await c.post(path, json={"data": data}, headers=headers)
    if r.is_error:
        raise RuntimeError(f"duffel {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


def to_option(offer: dict, date: str) -> dict:
    """A Duffel offer in the engine's option shape (see contract/mock-data.json)."""
    segs = offer["slices"][0]["segments"]
    first, last = segs[0], segs[-1]
    carrier = first["marketing_carrier"]
    return {
        "id": offer["id"], "offer_id": offer["id"], "source": "duffel",
        "airline": offer["owner"]["name"],
        "flight": f"{carrier['iata_code']}{first['marketing_carrier_flight_number']}",
        "departs": first["departing_at"][11:16], "arrives": last["arriving_at"][11:16],
        "day": "today" if last["arriving_at"][:10] == date else "tomorrow",
        "stops": len(segs) - 1,
        "price_usd": round(float(offer["total_amount"])), "currency": offer["total_currency"],
        "total_amount": offer["total_amount"], "passenger_id": offer["passengers"][0]["id"],
        "mcc": MCC_AIRLINE,
    }


async def search(origin: str, dest: str, date: str) -> list[dict]:
    """Cheapest few one-way economy offers for one adult, as engine options."""
    req = await _post("/air/offer_requests?return_offers=true&supplier_timeout=15000", {
        "slices": [{"origin": origin, "destination": dest, "departure_date": date}],
        "passengers": [{"type": "adult"}], "cabin_class": "economy", "max_connections": 0})
    offers = sorted(req["offers"], key=lambda o: float(o["total_amount"]))
    seen, out = set(), []
    for o in offers:
        opt = to_option(o, date)
        if opt["flight"] not in seen:  # one fare per flight
            seen.add(opt["flight"])
            out.append(opt)
    return out[:MAX_OPTIONS]


async def book(option: dict) -> dict:
    """Create a real (test-mode) order for the option; paid from the Duffel test balance."""
    order = await _post("/air/orders", {
        "type": "instant", "selected_offers": [option["offer_id"]],
        "passengers": [{**PASSENGER, "id": option["passenger_id"]}],
        "payments": [{"type": "balance", "currency": option["currency"], "amount": option["total_amount"]}]})
    return {"order_id": order["id"], "pnr": order["booking_reference"], "source": "duffel"}


if __name__ == "__main__":
    async def main():
        from datetime import date
        opts = await search("LAX", "SFO", date.today().isoformat())
        for o in opts:
            print(o["airline"], o["flight"], o["departs"], "->", o["arrives"], o["day"], o["price_usd"], o["currency"])
        if opts:
            print("booked:", await book(opts[0]))

    asyncio.run(main())
