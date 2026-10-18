"""Real flight status via FlightAware AeroAPI (https://www.flightaware.com/aeroapi/)."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

AEROAPI_KEY = os.getenv("AEROAPI_KEY")
AEROAPI_URL = "https://aeroapi.flightaware.com/aeroapi"


def _local_hhmm(iso: str | None, tz: str | None) -> str | None:
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t.astimezone(ZoneInfo(tz)).strftime("%H:%M") if tz else t.strftime("%H:%M")


def normalize(f: dict) -> dict:
    """AeroAPI flight object -> the few fields we care about."""
    origin, dest = f.get("origin") or {}, f.get("destination") or {}
    tz = origin.get("timezone")
    return {
        "flight": f.get("ident_iata") or f.get("ident"),
        "route": f"{origin.get('code_iata')}-{dest.get('code_iata')}",
        "status": f.get("status"),
        "cancelled": bool(f.get("cancelled")),
        "gate": f.get("gate_origin"),
        "terminal": f.get("terminal_origin"),
        "delay_min": (f.get("departure_delay") or 0) // 60,
        "departure": _local_hhmm(f.get("estimated_out") or f.get("scheduled_out"), tz),
        "arrival": _local_hhmm(f.get("estimated_in") or f.get("scheduled_in"), dest.get("timezone")),
    }


def pick_current(flights: list[dict]) -> dict | None:
    """AeroAPI returns past and future legs; we want the next one that hasn't arrived."""
    upcoming = [f for f in flights if not f.get("actual_in")]
    if upcoming:
        return min(upcoming, key=lambda f: f.get("scheduled_out") or "")
    return flights[0] if flights else None


# ponytail: fake flight used when AEROAPI_KEY is unset; edit it via POST /simulate/flight
FAKE = {"flight": "UA183", "route": "LAX-SFO", "status": "Scheduled", "cancelled": False,
        "gate": "52", "terminal": "7", "delay_min": 0, "departure": "18:10", "arrival": "19:35"}


async def fetch_status(flight: str) -> dict | None:
    if not AEROAPI_KEY:
        return {**FAKE, "flight": flight}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{AEROAPI_URL}/flights/{flight}", headers={"x-apikey": AEROAPI_KEY})
        r.raise_for_status()
    f = pick_current(r.json().get("flights", []))
    return normalize(f) if f else None


def diff(old: dict | None, new: dict) -> list[tuple[str, dict]]:
    """Compare two snapshots -> list of (event_type, data) to publish."""
    if old is None:
        return []
    events = []
    if new["cancelled"] and not old["cancelled"]:
        events.append(("flight.cancelled", {"flight": new["flight"], "route": new["route"]}))
    if new["gate"] and old["gate"] and new["gate"] != old["gate"]:
        events.append(("gate.changed", {"flight": new["flight"], "old_gate": old["gate"], "new_gate": new["gate"]}))
    # ponytail: 15-min threshold avoids alert spam from minute-by-minute estimate jitter
    if new["delay_min"] >= 15 and new["delay_min"] - old["delay_min"] >= 15:
        events.append(("flight.delayed", {"flight": new["flight"], "minutes": new["delay_min"],
                                          "new_departure": new["departure"]}))
    return events
