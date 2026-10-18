"""Live flight status through FlightAware AeroAPI (needs AEROAPI_KEY).

Try it:  cd engine && python -m app.status UA1
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

API = "https://aeroapi.flightaware.com/aeroapi"


def enabled() -> bool:
    return bool(os.getenv("AEROAPI_KEY"))


def _local(iso: str | None, tz: str | None) -> str | None:
    """'2026-10-18T04:10:00Z' -> local 'HH:MM' at the airport."""
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    try:
        return t.astimezone(ZoneInfo(tz)).strftime("%H:%M") if tz else t.strftime("%H:%M UTC")
    except ZoneInfoNotFoundError:
        return t.strftime("%H:%M UTC")


def normalize(f: dict) -> dict:
    origin, dest = f.get("origin") or {}, f.get("destination") or {}
    otz, dtz = origin.get("timezone"), dest.get("timezone")
    return {
        "flight": f.get("ident_iata") or f.get("ident"), "airline": f.get("operator_iata") or f.get("operator"),
        "route": f"{origin.get('code_iata')}-{dest.get('code_iata')}",
        "from": origin.get("city"), "to": dest.get("city"),
        "status": f.get("status"), "cancelled": bool(f.get("cancelled")), "diverted": bool(f.get("diverted")),
        "departure_delay_min": (f.get("departure_delay") or 0) // 60,
        "gate": f.get("gate_origin"), "terminal": f.get("terminal_origin"),
        "arrival_gate": f.get("gate_destination"), "baggage": f.get("baggage_claim"),
        "scheduled_departure": _local(f.get("scheduled_out"), otz),
        "estimated_departure": _local(f.get("actual_out") or f.get("estimated_out"), otz),
        "scheduled_arrival": _local(f.get("scheduled_in"), dtz),
        "estimated_arrival": _local(f.get("actual_in") or f.get("estimated_in"), dtz),
        "date": (f.get("scheduled_out") or "")[:10], "aircraft": f.get("aircraft_type"),
        "progress_percent": f.get("progress_percent"), "source": "flightaware",
    }


def pick_current(flights: list[dict]) -> dict | None:
    """AeroAPI returns past and future legs; take the next one that hasn't arrived, else the latest."""
    upcoming = [f for f in flights if not f.get("actual_in")]
    if upcoming:
        return min(upcoming, key=lambda f: f.get("scheduled_out") or "")
    return max(flights, key=lambda f: f.get("scheduled_out") or "") if flights else None


async def fetch(flight: str) -> dict:
    """Current status of a flight number like 'UA1' or 'DL1946'. Raises on HTTP errors."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/flights/{flight.replace(' ', '').upper()}",
                        headers={"x-apikey": os.environ["AEROAPI_KEY"]})
    if r.status_code == 404:
        return {"flight": flight, "status": "not found", "source": "flightaware"}
    r.raise_for_status()
    f = pick_current(r.json().get("flights", []))
    return normalize(f) if f else {"flight": flight, "status": "no flights scheduled", "source": "flightaware"}


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    print(asyncio.run(fetch(sys.argv[1] if len(sys.argv) > 1 else "UA1")))
