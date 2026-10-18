"""Live flight status through FlightAware AeroAPI (needs AEROAPI_KEY).

Try it:  cd engine && python -m app.status UA1
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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


def _local_date(iso: str | None, tz: str | None) -> str:
    """Departure date at the origin airport (a 6 PM LA flight is the next day in UTC)."""
    if not iso:
        return ""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    try:
        return t.astimezone(ZoneInfo(tz)).date().isoformat() if tz else iso[:10]
    except ZoneInfoNotFoundError:
        return iso[:10]


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
        "date": _local_date(f.get("scheduled_out"), otz), "aircraft": f.get("aircraft_type"),
        "progress_percent": f.get("progress_percent"), "source": "flightaware",
        "fa_flight_id": f.get("fa_flight_id"),  # pins this exact leg for later lookups
    }


def _icao(code: str) -> str:
    """US IATA airport code -> ICAO (LAX -> KLAX); the airports endpoints want ICAO."""
    code = code.upper()
    return f"K{code}" if len(code) == 3 else code


async def next_departure(origin: str, dest: str, prefer: str = "UA", min_ahead_min: int = 30,
                         window_h: int = 12) -> dict | None:
    """The next real nonstop origin->dest flight that hasn't left yet, preferring one airline.

    Used for free mode: the traveler's own flight is a real one, so questions about it get live answers.
    Returns a normalized flight (see normalize) or None if nothing is scheduled. Raises on HTTP errors.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda t: t.isoformat().replace("+00:00", "Z")  # noqa: E731
    params = {"start": iso(now + timedelta(minutes=min_ahead_min)), "end": iso(now + timedelta(hours=window_h)),
              "connection": "nonstop", "type": "Airline", "max_pages": 1}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/airports/{_icao(origin)}/flights/to/{_icao(dest)}", params=params,
                        headers={"x-apikey": os.environ["AEROAPI_KEY"]})
    r.raise_for_status()
    legs = [f["segments"][0] for f in r.json().get("flights", []) if f.get("segments")]
    legs = sorted((s for s in legs if not s.get("cancelled") and s.get("scheduled_out")),
                  key=lambda s: s["scheduled_out"])
    if not legs:
        return None
    best = next((s for s in legs if (s.get("operator_iata") or "") == prefer), legs[0])
    return normalize(best)


def pick_current(flights: list[dict]) -> dict | None:
    """AeroAPI returns past and future legs; take the next one that hasn't arrived, else the latest.
    Legs scheduled over a day ago are never "upcoming", even if AeroAPI never recorded their arrival."""
    stale = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    upcoming = [f for f in flights if not f.get("actual_in") and (f.get("scheduled_out") or "") >= stale]
    if upcoming:
        return min(upcoming, key=lambda f: f.get("scheduled_out") or "")
    return max(flights, key=lambda f: f.get("scheduled_out") or "") if flights else None


async def fetch(flight: str, fa_flight_id: str | None = None) -> dict:
    """Current status of a flight number like 'UA1' or 'DL1946', or of one exact leg (fa_flight_id).
    Raises on HTTP errors."""
    ident = fa_flight_id or flight.replace(" ", "").upper()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/flights/{ident}", headers={"x-apikey": os.environ["AEROAPI_KEY"]})
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
