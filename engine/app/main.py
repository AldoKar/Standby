"""Handle It engine: FastAPI + SSE.

Runs the whole demo flow on mock data (contract/mock-data.json), so the glasses,
agents and dashboard can be built against it today. Contract: contract/events.md
and contract/api.md. Owner: P1.

Run from engine/:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, call, claims, flights, policy, status, tap, verify, voice
from .call import start_call

ROOT = Path(__file__).resolve().parents[2]
MOCK = json.loads((ROOT / "contract" / "mock-data.json").read_text())
DASHBOARD = ROOT / "dashboard" / "index.html"
CALL_MODE = os.getenv("CALL_MODE", "mock")  # mock | elevenlabs
HEARTBEAT_S = 15
MOCK_CLERK_DELAY_S = float(os.getenv("MOCK_CLERK_DELAY_S", "4"))  # clerk asks for the fee
MOCK_CALL_END_S = float(os.getenv("MOCK_CALL_END_S", "2"))  # call wraps up after the answer
CLAIM_DELAY_S = float(os.getenv("CLAIM_DELAY_S", "6"))  # the outcome stays on the glasses before the claim
BENEFITS = MOCK["travel_benefits"]

# Free mode: the traveler's own flight is a real one (FlightAware), so questions about it get live answers;
# Start then "cancels" that same flight and the usual flow runs. auto = next real LAX->SFO nonstop
# (United first); a flight number pins one (it should fly LAX->SFO); off = the mock UA183.
LIVE_FLIGHT = os.getenv("LIVE_FLIGHT", "auto").strip()
LIVE_REFRESH_S = 30 * 60  # look again after a reset if the last lookup is older (the flight may have left)
AIRLINES = {"UA": "United", "AA": "American", "DL": "Delta", "AS": "Alaska", "WN": "Southwest", "B6": "JetBlue",
            "F9": "Frontier", "NK": "Spirit", "HA": "Hawaiian", "OO": "SkyWest", "QX": "Horizon"}
TRIP: dict = {"booking": None, "fetched": 0.0, "error": None}  # survives demo resets
BACKGROUND: set[asyncio.Task] = set()  # not cancelled by S.reset()

app = FastAPI(title="Handle It engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- state ----------

class State:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self.jobs: set[asyncio.Task] = set()
        self.reset()

    def reset(self) -> None:
        for job in getattr(self, "jobs", set()):
            job.cancel()
        self.jobs = set()
        self.task_id: str | None = None
        self.stage = "ready"  # ready, cancelled, offer, booked, calling, fee, resolved
        self.mandate = policy.Mandate.from_dict(MOCK["mandate"])
        self.ledger = policy.Ledger()
        self.options: list[dict] = []
        self.flights_source, self.flights_error = "mock", None
        self.flow_source: str | None = None  # glasses / simulate / asi1
        self.raw_options: list[dict] = []  # unranked, so a new spending limit can re-rank them
        self.proposal: dict | None = None  # the spending limit offered at cancellation (budget consent)
        self.budget_draft: dict | None = None  # a budget the traveler said, waiting for the confirm tap
        self.choices: list[dict] = []  # the flights listed on the glasses, recommended first
        self.cursor = 0  # which of them is highlighted
        self.pick: dict | None = None
        self.approvals: dict[str, dict] = {}
        self.fee_allowance = 0.0
        self.outcome: dict | None = None
        self.screen: dict = ready_screen()
        self.vault: list[dict] = seed_vault()
        self.agent_log: list[dict] = []  # what Claude did this task: thoughts, tool calls, results
        self.call_started = False
        self.before_answer: dict | None = None  # the screen an /ask answer covered
        self.claim: dict | None = None  # the travel-benefit claim for this trip (claims.py)
        self.claim_drafting = False
        self.claim_rush: asyncio.Event | None = None  # set when the wearer taps past the outcome: show the claim now


def booking() -> dict:
    """The traveler's booked flight: the live one found for free mode, else the mock UA183."""
    return TRIP["booking"] or MOCK["booking"]


def seed_vault() -> list[dict]:
    """What the traveler saved before the trip (pre-seeded, per the SPEC). The flow adds to it."""
    b, lodging = booking(), MOCK["lodging"]
    return [
        {"id": "vlt-ua183", "type": "boarding_pass", "title": f"{b['airline']} {b['flight']} {b['from']}-{b['to']}",
         "saved_at": None, "source": "traveler",
         "data": {k: b[k] for k in ("airline", "flight", "from", "to", "date", "departs", "pnr")}},
        {"id": "vlt-lodging", "type": "lodging_confirmation", "title": lodging["name"],
         "saved_at": None, "source": "traveler",
         "data": {"name": lodging["name"], "confirmation": lodging["confirmation"],
                  "desk_closes": lodging["desk_closes"], "note": lodging["note"]}},
        {"id": "vlt-benefits", "type": "travel_benefits", "title": BENEFITS["program"],
         "saved_at": None, "source": "traveler", "data": BENEFITS},
    ]


async def save_to_vault(type_: str, title: str, data: dict) -> dict:
    item = {"id": f"vlt-{uuid.uuid4().hex[:8]}", "type": type_, "title": title,
            "saved_at": now(), "source": "agent", "data": data}
    S.vault.append(item)
    await publish("vault.updated", {"type": type_, "id": item["id"], "title": title})
    return item


def ready_screen() -> dict:
    """Free mode. With Claude available, a long press is push-to-talk for a free question (the glasses
    record it and send it to POST /ask); a tap starts the disruption flow as always."""
    if agent.can_ask():
        return {"screen_id": "ready", "lines": ["Ready", "Tap = start, Hold = ask"],
                "gestures": {"press": "start", "hold": "ask"}, "clear_after_s": None}
    return {"screen_id": "ready", "lines": ["Ready", "Tap to start"], "gestures": {"press": "start"}, "clear_after_s": None}


async def show_ready() -> None:
    S.screen = ready_screen()
    await publish("hud.screen", S.screen)


async def load_live_flight(force: bool = False) -> None:
    """Find the real flight for free mode. Any failure keeps the current (or mock) flight."""
    if LIVE_FLIGHT.lower() == "off" or not status.enabled():
        return
    if not force and TRIP["booking"] and asyncio.get_running_loop().time() - TRIP["fetched"] < LIVE_REFRESH_S:
        return
    b = MOCK["booking"]
    try:
        f = await (status.next_departure(b["from"], b["to"]) if LIVE_FLIGHT.lower() == "auto"
                   else status.fetch(LIVE_FLIGHT))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        TRIP["error"] = f"flightaware: {e}"[:200]
        return
    departs = (f or {}).get("scheduled_departure") or ""
    if not f or not f.get("flight") or not re.fullmatch(r"\d{2}:\d{2}", departs):
        TRIP["error"] = f"no live flight found ({(f or {}).get('status', 'nothing scheduled')})"
        return
    if S.task_id is not None:  # never swap the flight under a running task; the next reset picks it up
        return
    code = f.get("airline") or ""
    TRIP.update(booking={**b, "airline": AIRLINES.get(code, code or b["airline"]), "flight": f["flight"],
                         "departs": departs, "date": f.get("date") or b["date"], "live": True,
                         "fa_flight_id": f.get("fa_flight_id")},
                fetched=asyncio.get_running_loop().time(), error=None)
    S.vault = [seed_vault()[0], *S.vault[1:]]
    t = TRIP["booking"]
    await publish("trip.updated", {"airline": t["airline"], "flight": t["flight"], "route": f"{t['from']}-{t['to']}",
                                   "date": t["date"], "departs": t["departs"], "source": "flightaware"})


def refresh_live_flight(force: bool = False) -> None:
    job = asyncio.create_task(load_live_flight(force))
    BACKGROUND.add(job)
    job.add_done_callback(BACKGROUND.discard)


S = State()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fit(line: str, short: str) -> str:
    """Glasses lines are at most 24 chars: long live airline names fall back to the flight number."""
    return line if len(line) <= 24 else short


def hhmm(t: str, ampm: bool = True) -> str:
    h, m = (int(x) for x in t.split(":"))
    clock = f"{h % 12 or 12}:{m:02d}"
    return f"{clock} {'PM' if h >= 12 else 'AM'}" if ampm else clock


def run_later(coro) -> None:
    job = asyncio.create_task(coro)
    S.jobs.add(job)
    job.add_done_callback(S.jobs.discard)


async def publish(type_: str, data: dict | None = None) -> dict:
    event = {"type": type_, "ts": now(), "task_id": S.task_id, "data": data or {}}
    for q in list(S.subscribers):
        q.put_nowait(event)
    return event


async def show(screen_id: str, lines: list[str], gestures: dict | None = None, clear_after_s: int | None = None) -> None:
    S.screen = {"screen_id": screen_id, "lines": lines[:3], "gestures": gestures or {}, "clear_after_s": clear_after_s}
    await publish("hud.screen", S.screen)


def snapshot() -> dict:
    return {
        "task_id": S.task_id,
        "stage": S.stage,
        "screen": S.screen,
        "options": S.options,
        "pick": S.pick,
        "approvals": list(S.approvals.values()),
        "outcome": S.outcome,
        "ledger": S.ledger.view(S.mandate),
        "vault": S.vault,
        "agent": S.agent_log,
        "claim": S.claim,
        "call_mode": CALL_MODE,
        "trip": {**booking(), "live": bool(booking().get("live")), "error": TRIP["error"]},
    }


# ---------- the flow ----------

async def start_flow(source: str) -> None:
    S.task_id = f"task-{uuid.uuid4().hex[:8]}"
    S.flow_source = source
    S.stage = "searching"
    b, offer = booking(), MOCK["airline_offer"]
    await publish("flight.cancelled", {"flight": b["flight"], "route": f"{b['from']}-{b['to']}",
                                       "airline_offer": offer, "source": source})
    await show("searching", [f"{b['flight']} cancelled", "Finding flights..."])
    if not (agent.enabled() and await plan_with_agent(b)):
        await search(b["from"], b["to"])
        S.pick = next((o for o in S.options if o["verdict"] == "pick"), None)
    await publish("options.ranked", {"options": S.options, "source": S.flights_source, "error": S.flights_error,
                                      "chosen_by": "agent" if S.pick and S.pick.get("chosen_by") == "agent" else "policy"})
    S.proposal = S.proposal or propose_limit()
    await publish("budget.proposed", S.proposal)
    await show_consent()
    S.stage = "cancelled"


async def show_consent() -> None:
    """Budget consent at the moment it matters: the agent asks once for a spending limit it chose from
    tonight's prices, instead of the traveler setting rules before every trip."""
    b = booking()
    await show("cancelled", [f"{b['flight']} cancelled", f"Fix it for up to ${S.proposal['limit_usd']:g}?",
                             "Tap = yes, Hold = budget, Swipe = no"],
               {"press": "fix", "hold": "budget", "swipe_down": "no"})


async def ask_budget() -> None:
    """Hold on the budget consent (or "change the budget"): the traveler says the amount they want."""
    await show("budget_ask", ["New budget?", "Say an amount", "Tap = back"], {"press": "back"})


def traveler_budget(amount: float) -> dict:
    """The limit the traveler asked for, kept between the cheapest on-time fare and LIMIT_MAX_USD (no rounding:
    they named the number). Same shape as propose_limit()."""
    fares = sorted(o["price_usd"] for o in on_time(S.raw_options or S.options) if o["price_usd"] > 0)
    low, high = (fares[0], fares[-1]) if fares else (0, 0)
    limit = float(min(LIMIT_MAX_USD, max(low, round(amount))))
    return {"limit_usd": limit, "ask_over_usd": S.mandate.ask_over_usd, "fares_usd": [low, high],
            "reason": f"You set ${limit:g} on the glasses.", "proposed_by": "traveler", "asked_usd": amount}


async def confirm_budget(amount: float) -> None:
    """The traveler said a budget: show it for a tap (confirm) or a swipe (roll back to the proposed one)."""
    S.budget_draft = draft = traveler_budget(amount)
    limit, low = draft["limit_usd"], draft["fares_usd"][0]
    if amount < low:
        note = f"Lowest fare ${low:g}"
    elif amount > LIMIT_MAX_USD:
        note = f"Max ${LIMIT_MAX_USD:g}"
    else:
        note = f"Was ${S.proposal['limit_usd']:g}"
    await publish("budget.requested", {"asked_usd": amount, "limit_usd": limit, "was_usd": S.proposal["limit_usd"]})
    await show("budget_confirm", [f"Budget ${limit:g}?", note, "Tap = confirm, Swipe = roll back"],
               {"press": "confirm", "swipe_down": "roll back"})


LIMIT_STEP = 50  # limits are round numbers
LIMIT_EXTRAS_USD = 50  # headroom over the cheapest fare for fees on the way (late check-in, a meal)
LIMIT_MAX_USD = 1000


def on_time(options: list[dict]) -> list[dict]:
    """Options that get there by the deadline, whatever they cost."""
    return [o for o in options if o["day"] == "today" and o["arrives"] <= MOCK["deadline"]["arrive_by"]]


def propose_limit(amount: float | None = None, reason: str | None = None, by: str = "policy") -> dict:
    """The spending limit offered to the traveler. Claude may suggest the amount; code rounds it up and keeps
    it between the cheapest on-time fare and LIMIT_MAX_USD. Without a suggestion: cheapest fare plus extras."""
    fares = sorted(o["price_usd"] for o in on_time(S.raw_options or S.options) if o["price_usd"] > 0)
    low, high = (fares[0], fares[-1]) if fares else (0, 0)
    wanted = amount if amount and amount > 0 else low + LIMIT_EXTRAS_USD
    limit = min(LIMIT_MAX_USD, max(low, -(-wanted // LIMIT_STEP) * LIMIT_STEP))
    if not reason:
        span = f"${low:g}-${high:g}" if high > low else f"${low:g}"
        reason = (f"Flights that get you there tonight run {span}; ${limit:g} covers the flight plus fees on the way. "
                  f"I'll ask before anything over ${S.mandate.ask_over_usd:g}.")
    return {"limit_usd": limit, "ask_over_usd": S.mandate.ask_over_usd, "fares_usd": [low, high],
            "reason": reason[:400], "proposed_by": by}


async def accept_limit(via: str) -> None:
    """The traveler said yes: the mandate's budget becomes the proposed limit, and the flights are re-ranked
    under it (Claude's pick stays if it still fits)."""
    limit = S.proposal["limit_usd"]
    if S.mandate.budget_usd != limit:
        S.mandate.budget_usd = limit
        picked = S.pick or {}
        S.options = policy.rank_options(S.raw_options or S.options, S.mandate, S.ledger, MOCK["deadline"])
        keep = next((o for o in S.options if o["id"] == picked.get("id") and o["verdict"] != "rejected"), None)
        if keep:
            for o in S.options:
                o["verdict"] = "ok" if o["verdict"] == "pick" else o["verdict"]
            keep["verdict"] = "pick"
            keep.update({k: v for k, v in picked.items() if k in ("chosen_by", "agent_reason")})
        S.pick = keep or next((o for o in S.options if o["verdict"] == "pick"), None)
    S.mandate.instruction = (f"Get me to SF tonight. Up to ${limit:g} total. "
                             f"Ask me before any spend over ${S.mandate.ask_over_usd:g}.")
    await publish("mandate.set", {"budget_usd": limit, "ask_over_usd": S.mandate.ask_over_usd, "via": via,
                                  "reason": S.proposal["reason"], "proposed_by": S.proposal["proposed_by"]})


# ponytail: fixed PDT offset (the demo is in LA in October); zoneinfo if it ever runs elsewhere.
LA = timezone(timedelta(hours=-7))


async def find_options(origin: str, dest: str, date: str | None = None) -> tuple[list[dict], str, str | None]:
    """The airline's free rebooking plus live Duffel fares; mock fares if Duffel is off or fails."""
    if not flights.enabled():
        # ponytail: the glasses list three flights to choose from; ASI:One keeps the three-option set its
        # cards and tests are built on. One list for both once the orchestrator shows more.
        extra = MOCK["extra_options"] if S.flow_source in ("glasses", "simulate") else []
        return [*MOCK["options"], *extra], "mock", None
    now_la = datetime.now(LA)
    today = now_la.date().isoformat()
    try:
        live = await flights.search(origin, dest, date or today, today)
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError, IndexError) as e:
        return MOCK["options"], "mock", f"duffel: {e}"[:300]
    if not flights.test_mode() and (date or today) == today:  # test-mode schedules are made up
        live = [o for o in live if o["departs"] > now_la.strftime("%H:%M")]
    return [MOCK["options"][0], *live], "duffel", None


async def search(origin: str, dest: str, date: str | None = None) -> list[dict]:
    """Search and rank; the ranked options become the task's options."""
    S.raw_options, S.flights_source, S.flights_error = await find_options(origin, dest, date)
    S.options = policy.rank_options(S.raw_options, S.mandate, S.ledger, MOCK["deadline"])
    return S.options


# ---------- Claude as the agent (AGENT_MODE=claude) ----------

async def agent_step(step: dict) -> None:
    S.agent_log.append({**step, "ts": now()})
    await publish("agent.step", step)


async def run_agent(phase: str, facts: dict, tools: dict) -> bool:
    """True if Claude finished the phase; False (and logged) if it failed, so the scripted flow takes over."""
    try:
        said = await agent.run(phase, facts, tools, agent_step)
    except (anthropic.APIError, RuntimeError, TimeoutError, ValueError, KeyError) as e:
        await publish("agent.failed", {"phase": phase, "error": str(e)[:300]})
        return False
    await publish("agent.done", {"phase": phase, "text": said})
    S.agent_log.append({"phase": phase, "kind": "done", "text": said, "ts": now()})
    return True


TRIP_STATUS_TTL_S = 60  # one AeroAPI lookup per minute at most for the traveler's own flight
_trip_status: dict = {"at": -1e9, "data": None}


async def trip_live_status() -> dict:
    """Live status of the traveler's own (real) flight, pinned to the exact leg found for free mode."""
    b, loop = booking(), asyncio.get_running_loop()
    cached = _trip_status["data"]
    if cached and cached.get("flight") == b["flight"] and loop.time() - _trip_status["at"] < TRIP_STATUS_TTL_S:
        return cached
    try:
        live = await status.fetch(b["flight"], b.get("fa_flight_id"))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return {"flight": b["flight"], "airline": b["airline"], "route": f"{b['from']}-{b['to']}", "date": b["date"],
                "status": "scheduled", "scheduled_departure": b["departs"], "source": "trip",
                "live_error": str(e)[:200]}
    data = {**{k: v for k, v in live.items() if k != "fa_flight_id"}, "note": "the traveler's own booked flight"}
    _trip_status.update(at=loop.time(), data=data)
    return data


async def flight_status(flight: str) -> dict:
    """The trip's own flights answer from the trip; any other flight is live from FlightAware. In free mode
    (before Start) the traveler's flight is a real one, so it's live too; once the flow starts it's "cancelled"."""
    f, b = flight.replace(" ", "").upper(), booking()
    if f == b["flight"] and b.get("live") and S.task_id is None and status.enabled():
        return await trip_live_status()
    if f == b["flight"]:
        cancelled = S.task_id is not None
        return {"flight": f, "airline": b["airline"], "route": f"{b['from']}-{b['to']}", "date": b["date"],
                "status": "cancelled" if cancelled else "scheduled", "scheduled_departure": b["departs"],
                "airline_rebooking": MOCK["airline_offer"] if cancelled else None, "source": "trip"}
    o = next((o for o in [*S.options, *MOCK["options"]] if o["flight"] == f), None)
    if o:
        booked = S.pick is not None and S.pick["flight"] == f and S.stage not in ("cancelled", "offer", "searching")
        return {"flight": f, "airline": o["airline"], "route": f"{b['from']}-{b['to']}", "day": o["day"],
                "status": "booked for the traveler" if booked else "scheduled",
                "scheduled_departure": o["departs"], "scheduled_arrival": o["arrives"], "source": "trip"}
    if not status.enabled():
        return {"flight": f, "status": "unknown (no live status configured)"}
    try:
        return await status.fetch(f)
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return {"flight": f, "status": "unavailable", "error": str(e)[:200]}


async def read_vault(_: dict | None = None) -> dict:
    return {"items": [{"type": v["type"], "title": v["title"], "data": v["data"]} for v in S.vault]}


def brief(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "airline", "flight", "departs", "arrives", "day", "stops", "price_usd",
                                  "verdict", "reason")}


async def plan_with_agent(b: dict) -> bool:
    """Claude checks the flight, searches and chooses. False if it failed (the scripted plan runs instead)."""
    async def search_flights(i: dict) -> dict:
        found = await search(i["origin"].upper(), i["destination"].upper(), i.get("date"))
        return {"source": S.flights_source, "options": [brief(o) for o in found]}

    async def choose_flight(i: dict) -> dict:
        o = next((o for o in S.options if o["id"] == i["option_id"]), None)
        if not o:
            return {"error": f"no option {i['option_id']}; search first"}
        if o["verdict"] == "rejected":
            return {"refused": f"policy rejected it: {o['reason']}"}
        for x in S.options:
            x["verdict"] = "ok" if x["verdict"] == "pick" else x["verdict"]
        o.update(verdict="pick", chosen_by="agent", agent_reason=i["reason"])
        S.pick = o
        return {"chosen": f"{o['airline']} {o['flight']}", "next": "now propose a spending limit with propose_limit"}

    async def propose_limit_tool(i: dict) -> dict:
        if not S.options:
            return {"error": "search first"}
        S.proposal = propose_limit(float(i.get("amount_usd") or 0), str(i.get("reason", "")), "agent")
        return {"proposed": S.proposal["limit_usd"], "next": "the traveler accepts it with a tap on the glasses"}

    S.pick, S.proposal = None, None
    facts = {"traveler": MOCK["traveler"]["name"], "now": datetime.now(LA).isoformat(timespec="minutes"),
             "cancelled_booking": b, "mandate": S.mandate.instruction, "budget_left_usd": S.ledger.remaining(S.mandate),
             "deadline": MOCK["deadline"]}
    ok = await run_agent("plan", facts, {"check_flight_status": lambda i: flight_status(i["flight"]), "search_flights": search_flights,
                                         "read_vault": read_vault, "choose_flight": choose_flight,
                                         "propose_limit": propose_limit_tool})
    if ok and not S.options:  # finished without searching: rank anyway so the glasses have options
        await search(b["from"], b["to"])
    return ok


LIST_MAX = 3


def choice_line(o: dict, on: bool) -> str:
    """One row of the flight list, at most 24 chars: '> Delta 9:15 PM $215'."""
    when = f"{hhmm(o['departs'])} ${o['price_usd']:g}"
    label = f"{o['airline']} {when}"
    if len(label) > 22:  # 24 minus the mark: long airline names fall back to the flight number
        label = f"{o['flight']} {when}"
    return ("> " if on else "  ") + label[:22]


async def offer_choices() -> dict | None:
    """After the limit is accepted: up to three flights that fit it, the recommended one first and
    highlighted. With one flight left, the single offer screen as before."""
    fits = [o for o in S.options if o["verdict"] != "rejected"]
    fits.sort(key=lambda o: (o is not S.pick, o["arrives"], o["price_usd"]))
    S.choices, S.cursor = fits[:LIST_MAX], 0
    if len(S.choices) < 2:
        return await offer_pick()
    return await offer_highlighted()


async def offer_highlighted() -> dict:
    """The booking approval for the highlighted flight, shown as the list. Swipe moves the highlight
    (a new approval for the next flight); hold books the one highlighted."""
    p = S.pick = S.choices[S.cursor]
    S.stage = "offer"
    lines = [choice_line(o, i == S.cursor) for i, o in enumerate(S.choices)]
    return await request_spend(
        "booking", p["price_usd"], p["airline"], p["mcc"], f"{p['airline']} {p['flight']} tonight",
        screen=("flight_list", lines, {"hold": "book", "swipe_down": "next", "select": "highlight"}))


async def next_choice() -> None:
    """Swipe on the list (dashboard, browser): the next row."""
    await select_choice((S.cursor + 1) % len(S.choices))


async def select_choice(index: int) -> None:
    """Highlight one row: withdraw the current flight's approval and ask for this one. The glasses' native
    list owns the selection and reports every move (`select`); the same row again changes nothing."""
    if index == S.cursor and pending("booking"):
        return
    a = pending("booking")
    if a:
        a["status"] = "withdrawn"
        await publish("approval.withdrawn", {"approval_id": a["approval_id"], "kind": "booking", "reason": "other option"})
    S.cursor = index
    if S.cursor:
        S.choices[S.cursor]["chosen_by"] = "traveler"
    await offer_highlighted()


async def offer_pick() -> dict | None:
    p = S.pick
    if not p:
        await show("no_option", ["No flight tonight", "fits your budget"], {}, 10)
        return None
    S.stage = "offer"
    return await request_spend(
        "booking", p["price_usd"], p["airline"], p["mcc"], f"{p['airline']} {p['flight']} tonight",
        screen=("booking_offer",
                [fit(f"{p['airline']} tonight {hhmm(p['departs'])}", f"{p['flight']} tonight {hhmm(p['departs'])}"),
                 f"${p['price_usd']} · lands {hhmm(p['arrives'], False)}", "Hold to book"],
                {"hold": "approve", "swipe_down": "other"}),
    )


async def request_spend(kind: str, amount: float, merchant: str, mcc: str, reason: str, screen: tuple) -> dict:
    """One path for every spend: mandate check, then pay silently, deny, or ask the wearer."""
    decision, why, line = policy.check_spend(S.mandate, S.ledger, amount, mcc, S.fee_allowance if kind == "fee" else 0)
    await publish("mandate.checked", {"kind": kind, "amount": amount, "remaining": S.ledger.remaining(S.mandate),
                                      "result": decision, "reason": why})
    a = {"approval_id": f"apr-{uuid.uuid4().hex[:8]}", "task_id": S.task_id, "kind": kind, "amount": amount,
         "merchant": merchant, "mcc": mcc, "reason": reason, "status": "pending"}
    S.approvals[a["approval_id"]] = a
    if decision == "deny":
        a["status"] = "denied"
        S.ledger.denied.append({"amount": amount, "merchant": merchant, "reason": why, "ts": now()})
        await show("denied", [f"${amount:g} {reason}"[:24], line, "Confirm on phone"], {}, 8)
        await after_answer(a)
        return a
    if decision == "allow":
        a["status"] = "approved"
        await pay(a)
        await after_answer(a)
        return a
    await publish("approval.requested", {k: a[k] for k in ("approval_id", "kind", "amount", "merchant", "reason")})
    if kind == "fee":
        S.stage = "fee"
    await show(*screen)
    return a


async def answer(approval_id: str, approved: bool, via: str) -> dict:
    a = S.approvals.get(approval_id)
    if not a:
        raise HTTPException(404, f"no approval {approval_id}")
    if a["status"] != "pending":
        return a
    a["status"] = "approved" if approved else "rejected"
    S.ledger.consents.append({"approval_id": approval_id, "gesture": via, "approved": approved,
                              "amount": a["amount"], "merchant": a["merchant"], "ts": now()})
    await publish("approval.granted" if approved else "approval.rejected",
                  {"approval_id": approval_id, "kind": a["kind"], "via": via})
    if approved:
        await pay(a)
    await after_answer(a)
    return a


async def pay(a: dict) -> None:
    ref = f"VIC-{uuid.uuid4().hex[:8].upper()}"
    # Signed request to the (mock) merchant, which checks it the way a TAP merchant would.
    authority = re.sub(r"[^a-z0-9]+", "-", a["merchant"].lower()).strip("-") + ".merchant.example"
    body = {"merchant": a["merchant"], "amount": a["amount"], "mcc": a["mcc"],
            "token_id": S.mandate.token_id, "reference": ref}
    raw, headers = tap.sign(authority, "/agent/pay", body)
    ok, why = tap.verify(authority, "/agent/pay", raw, headers)
    signature = {"keyid": tap.KEY_ID, "tag": tap.TAG, "alg": "ed25519", "verified": ok, "reason": why,
                 "signature_input": headers["Signature-Input"], "signature": headers["Signature"]}
    S.ledger.spends.append({"amount": a["amount"], "merchant": a["merchant"], "mcc": a["mcc"],
                            "kind": a["kind"], "reference": ref, "ts": now(), "signature": signature})
    await publish("payment.executed", {"amount": a["amount"], "merchant": a["merchant"], "mcc": a["mcc"],
                                       "token_id": S.mandate.token_id, "reference": ref,
                                       "signature": {k: signature[k] for k in ("keyid", "tag", "verified")}})


async def after_answer(a: dict) -> None:
    if a["kind"] == "booking":
        if a["status"] == "approved":
            run_later(after_booking())
        else:
            S.stage = "cancelled"
            await show("cancelled", ["Not booked", "Tap = see it again"], {"press": "fix"})
    elif a["kind"] == "fee":
        if S.stage == "fee":  # the wearer answered on the glasses: leave the fee screen, the call goes on
            S.stage = "calling"
            first = f"+${a['amount']:g} OK" if a["status"] == "approved" else "Fee declined"
            await show("call_resumed", [first, "Finishing the call"])
        if CALL_MODE == "mock":
            run_later(mock_call_finish(a["status"] == "approved"))


async def book_pick(p: dict) -> dict:
    """A real Duffel order for a live fare; mock fares (or a failed order) get none."""
    if p.get("source") != "duffel":
        return {"source": "mock", "order_id": None, "pnr": None}
    try:
        return await flights.book(p)
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as e:
        return {"source": "duffel", "order_id": None, "pnr": None, "error": f"{e}"[:300]}


async def after_booking() -> None:
    p, offer, lodging = S.pick, MOCK["airline_offer"], MOCK["lodging"]
    S.stage = "booked"
    refund = MOCK["refund"]
    S.ledger.refunds.append({"amount": refund["amount_usd"], "airline": refund["airline"], "rule": refund["rule"],
                             "status": "pending", "ts": now()})
    await publish("offer.declined", {"airline": offer["airline"], "flight": offer["flight"],
                                     "refund_usd": refund["amount_usd"], "status": "pending"})
    paid = next((s for s in reversed(S.ledger.spends) if s["kind"] == "booking"), {})
    b = booking()
    order = await book_pick(p)
    await publish("flight.booked", {"airline": p["airline"], "flight": p["flight"], **order})
    await save_to_vault("boarding_pass", f"{p['airline']} {p['flight']} {b['from']}-{b['to']}", {
        "airline": p["airline"], "flight": p["flight"], "from": b["from"], "to": b["to"], "date": b["date"],
        "departs": p["departs"], "arrives": p["arrives"], "price_usd": p["price_usd"],
        "payment_reference": paid.get("reference"), "replaces": b["flight"],
        "pnr": order.get("pnr"), "order_id": order.get("order_id"), "booked_via": order["source"]})
    await show("booked", [f"Booked · PNR {order['pnr']}", "Pass saved"] if order.get("pnr") else ["Booked · pass saved"])
    await asyncio.sleep(1.5)
    if agent.enabled() and await arrival_with_agent():
        if not S.call_started:  # Claude decided no call is needed
            S.stage = "resolved"
            await publish("task.resolved", {"flight": p["flight"], "lodging": None})
            await show_outcome("resolved", ["All set", "No call needed"])
        return
    if not S.call_started:
        await call_lodging()


async def arrival_with_agent() -> bool:
    """Claude checks the arrival against the lodging and decides whether to call. False if it failed."""
    p, lodging = S.pick, MOCK["lodging"]

    async def check_arrival(_: dict) -> dict:
        eta = policy.arrival_eta(p["arrives"], lodging["travel_minutes_from_airport"])
        return {"flight": f"{p['airline']} {p['flight']}", "lands": p["arrives"], "lands_day": p["day"],
                "lodging": lodging["name"], "confirmation": lodging["confirmation"], "note": lodging["note"],
                "travel_minutes": lodging["travel_minutes_from_airport"], "eta_at_lodging": eta,
                "desk_closes": lodging["desk_closes"], "arrives_after_desk_closes": eta > lodging["desk_closes"]}

    async def call_lodging_tool(i: dict) -> dict:
        if S.call_started:
            return {"error": "already called"}
        S.call_started = True
        run_later(call_lodging(i.get("reason")))
        return {"status": "calling", "next": "the outcome reaches the traveler when the call ends"}

    facts = {"traveler": MOCK["traveler"]["name"], "booked_flight": brief(p), "lodging": lodging["name"]}
    return await run_agent("arrival", facts, {"check_arrival": check_arrival, "call_lodging": call_lodging_tool})


async def call_lodging(reason: str | None = None) -> None:
    p, lodging = S.pick, MOCK["lodging"]
    S.call_started = True
    eta = policy.arrival_eta(p["arrives"], lodging["travel_minutes_from_airport"])
    await publish("cutoff.detected", {"place": lodging["name"], "closes_at": lodging["desk_closes"],
                                      "arrival": p["arrives"], "eta": eta})
    await show("calling", [f"Desk closes {hhmm(lodging['desk_closes'])}", f"You land {hhmm(p['arrives'], False)}",
                           "Calling guesthouse"])
    S.stage = "calling"
    variables = {"guest_name": MOCK["traveler"]["name"], "confirmation": lodging["confirmation"],
                 "eta": hhmm(eta), "task_id": S.task_id}
    await publish("call.started", {"to": lodging["name"], "purpose": reason or "hold the room for a late arrival",
                                   "mode": CALL_MODE})
    if CALL_MODE == "elevenlabs":
        try:
            await start_call(variables)
        except Exception as e:  # keep the demo alive; the dashboard can play the recorded call
            await call_failed(str(e))
    else:
        await asyncio.sleep(MOCK_CLERK_DELAY_S)
        await request_fee(MOCK["call_script_mock"]["fee_usd"], MOCK["call_script_mock"]["fee_reason"])


async def call_failed(reason: str) -> None:
    """The call never connected: say so on the glasses instead of sitting on "Calling guesthouse"."""
    S.outcome = {"held": False, "error": reason, "verified": False}
    await publish("call.completed", {"outcome": S.outcome, "transcript_url": None, "verified": False})
    S.stage = "resolved"
    await show_outcome("call_failed", ["Call didn't connect", "Details on your phone"])


async def request_fee(amount: float, reason: str, merchant: str | None = None, mcc: str | None = None) -> dict:
    lodging = MOCK["lodging"]
    return await request_spend(
        "fee", amount, merchant or lodging["name"], mcc or lodging["mcc"], reason,
        screen=("fee_request", [f"+${amount:g} {reason}", "Guesthouse asks", "Hold = OK, Swipe = no"],
                {"hold": "approve", "swipe_down": "reject"}),
    )


async def mock_call_finish(approved: bool) -> None:
    await asyncio.sleep(MOCK_CALL_END_S)
    script = MOCK["call_script_mock"]
    await finish_call({"held": approved, "fee_usd": script["fee_usd"] if approved else 0,
                       "door_code": script["door_code"] if approved else None,
                       "contact": script["contact"], "verified": True,
                       "summary": "Simulated call: room held with a late check-in fee." if approved
                       else "Simulated call: fee declined, room not held."}, None)


async def finish_call(outcome: dict, transcript_url: str | None, transcript: str | None = None) -> None:
    S.outcome = outcome
    await publish("call.completed", {"outcome": outcome, "transcript_url": transcript_url,
                                     "verified": bool(outcome.get("verified"))})
    held, code = outcome.get("held"), outcome.get("door_code")
    await publish("task.resolved", {"flight": S.pick["flight"] if S.pick else None,
                                    "lodging": {"held": held, "door_code": code}})
    await save_to_vault("call_transcript", f"Call to {MOCK['lodging']['name']}", {
        "held": held, "door_code": code, "contact": outcome.get("contact"), "fee_usd": outcome.get("fee_usd"),
        "verified": bool(outcome.get("verified")), "summary": outcome.get("summary"),
        "issues": outcome.get("issues", []), "transcript": transcript, "transcript_url": transcript_url,
        "mode": CALL_MODE})
    S.stage = "resolved"
    screen_id = "resolved"
    if held and code and outcome.get("verified"):
        lines = ["Room held", f"Door code {code}"]
    elif held:
        lines = ["Room held", "Door code on phone"]  # never show an unverified code
    else:
        screen_id, lines = "not_held", ["Room not held", "Details on your phone"]
    await show_outcome(screen_id, lines)


# ---------- travel-benefit claim ----------

async def show_outcome(screen_id: str, lines: list[str]) -> None:
    """The trip's outcome (room held, not held, call failed, all set). If money can come back, the claim is
    drafted meanwhile and follows on its own; a tap (or "OK") skips ahead to it instead of ending the trip,
    which used to drop the claim. Without a claim coming, a tap ends the trip as before."""
    start_claim()
    if S.claim_drafting:
        await show(screen_id, lines, {"press": "next"})  # no auto-clear: the claim replaces it
    else:
        await show(screen_id, lines, {"press": "dismiss"}, 10)


def start_claim() -> None:
    """Called when the trip resolves. Marks the claim as drafting right away, so GET /claim waits for it."""
    if S.claim or not S.ledger.spends:
        return
    S.claim_drafting = True
    S.claim_rush = asyncio.Event()
    run_later(prepare_claim(S.task_id))


async def prepare_claim(task_id: str | None) -> None:
    """After the trip is handled, get the traveler's money back: Claude drafts the claim from the benefits
    and receipts, claims.py checks every amount, and the wearer taps to submit. Scripted if Claude is off."""
    S.claim_drafting = True
    try:
        await draft_claim(task_id)
    finally:
        if S.task_id == task_id:
            S.claim_drafting = False
            if not S.claim and S.screen["screen_id"] in ("claim_drafting", "resolved", "not_held", "call_failed"):
                # Nothing the benefits cover (or drafting failed): the outcome's "next" now ends the trip.
                gestures = {"press": "dismiss"}
                if S.screen["screen_id"] == "claim_drafting":
                    await show("resolved", ["All set", "Nothing to claim"], gestures, 10)
                elif S.screen["gestures"] != gestures:
                    await show(S.screen["screen_id"], S.screen["lines"], gestures, 10)


async def draft_claim(task_id: str | None) -> None:
    shown_at = asyncio.get_running_loop().time() + CLAIM_DELAY_S  # Claude drafts while the outcome is shown
    rush = S.claim_rush
    filed: dict = {}

    async def read_ledger(_: dict) -> dict:
        return S.ledger.view(S.mandate)

    async def file_claim(i: dict) -> dict:
        items, problems = claims.validate(i.get("items", []), S.ledger, BENEFITS)
        if problems:
            return {"refused": problems}
        filed.update(items=items, letter=str(i.get("letter", ""))[:3000])
        return {"claim_ready": round(sum(x["amount_usd"] for x in items), 2),
                "next": "the traveler submits it with a tap"}

    drafted_by = "script"
    if agent.enabled() and await run_agent("claim", {"traveler": MOCK["traveler"]["name"],
                                                     "benefits_program": BENEFITS["program"]},
                                           {"read_vault": read_vault, "read_ledger": read_ledger,
                                            "file_claim": file_claim}) and filed:
        drafted_by = "agent"
    if S.task_id != task_id:
        return
    if not filed:
        items, problems = claims.validate(claims.draft(S.ledger, BENEFITS), S.ledger, BENEFITS)
        if problems:
            return  # nothing the benefits cover
        filed.update(items=items, letter=claim_letter(items))
    try:  # the outcome stays up for a moment, unless the wearer already tapped past it
        await asyncio.wait_for(rush.wait() if rush else asyncio.sleep(3600),
                               max(0.0, shown_at - asyncio.get_running_loop().time()))
    except asyncio.TimeoutError:
        pass
    if S.task_id != task_id or S.claim:  # dismissed meanwhile
        return
    total = round(sum(x["amount_usd"] for x in filed["items"]), 2)
    S.claim = {"claim_id": f"clm-{uuid.uuid4().hex[:8]}", "task_id": task_id, "status": "ready",
               "program": BENEFITS["program"], "label": BENEFITS["label"], "token_id": BENEFITS["token_id"],
               "items": filed["items"], "total_usd": total, "letter": filed["letter"], "drafted_by": drafted_by,
               "ts": now()}
    await save_to_vault("trip_claim", f"Trip claim: ${total:g}", S.claim)
    await publish("claim.ready", {k: S.claim[k] for k in ("claim_id", "total_usd", "items", "drafted_by", "program")})
    await show("claim_ready", ["Trip claim ready", f"${total:g} back expected", "Tap = submit"],
               {"press": "submit", "swipe_down": "later"})


def claim_letter(items: list[dict]) -> str:
    b = booking()
    lines = [f"Claim for {MOCK['traveler']['name']}: {b['airline']} {b['flight']} {b['from']}-{b['to']} on "
             f"{b['date']} was cancelled by the carrier."]
    lines += [f"- {i['benefit']}: ${i['amount_usd']:g} ({i['rule']}; receipt {i['reference']})" for i in items]
    lines.append(f"Total claimed: ${sum(i['amount_usd'] for i in items):g}. Receipts referenced above (signed payments).")
    return "\n".join(lines)


async def submit_claim(via: str) -> None:
    """The wearer tapped (or ASI:One sent) submit. Once only. ponytail: simulated submission; there's no
    public Visa claims API today (docs/TRAVEL-CLAIMS.md)."""
    c = S.claim
    if c["status"] == "submitted":
        return
    c.update(status="submitted", submitted_at=now(), submitted_via=via)
    S.ledger.claims.append({"claim_id": c["claim_id"], "total_usd": c["total_usd"], "status": "submitted",
                            "program": c["program"], "ts": c["submitted_at"]})
    await publish("claim.submitted", {"claim_id": c["claim_id"], "total_usd": c["total_usd"], "via": via})
    await show("claim_submitted", ["Claim submitted", f"${c['total_usd']:g} expected back", "Details on phone"],
               {"press": "dismiss"}, 10)


# ---------- SSE ----------

def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    S.subscribers.add(q)

    async def stream():
        try:
            yield sse({"type": "state.snapshot", "ts": now(), "task_id": S.task_id, "data": snapshot()})
            yield sse({"type": "hud.screen", "ts": now(), "task_id": S.task_id, "data": S.screen})
            while not await request.is_disconnected():
                try:
                    yield sse(await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S))
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            S.subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/events")
async def post_event(event: dict):
    return await publish(event.get("type", "custom"), event.get("data"))


# ---------- glasses, dashboard, demo ----------

class Gesture(BaseModel):
    gesture: str  # press | hold | swipe_down | select (native list on the glasses)
    screen_id: str | None = None
    # flight_list: the row the glasses' native list has selected. With `select` it moves the highlight;
    # with `hold` it must match the highlighted flight, or nothing is booked.
    index: int | None = None


def pending(kind: str | None = None) -> dict | None:
    for a in reversed(list(S.approvals.values())):
        if a["status"] == "pending" and (kind is None or a["kind"] == kind):
            return a
    return None


@app.post("/input")
async def input_(g: Gesture):
    stage, gesture = S.stage, g.gesture
    # A gesture made on a screen that's no longer shown (e.g. a slow "hold" meant for the booking
    # that lands on the fee screen) must not approve anything. Callers without screen_id
    # (dashboard buttons) keep working as before.
    if g.screen_id and g.screen_id != S.screen["screen_id"]:
        return {"handled": False, "stage": stage, "reason": f"stale screen: {g.screen_id}, now {S.screen['screen_id']}"}
    if gesture == "press" and S.screen["screen_id"] == "answer":
        await restore_screen(S.before_answer)
    elif S.screen["screen_id"] == "claim_ready" and gesture in ("press", "swipe_down"):
        if gesture == "press":
            await submit_claim("glasses")
        else:  # later: it stays ready in the Vault, submit from the phone
            await show("resolved", ["Claim saved", "Submit from phone"], {"press": "dismiss"}, 10)
    elif stage == "cancelled" and gesture == "hold" and S.screen["screen_id"] == "cancelled" and S.proposal:
        await ask_budget()
    elif S.screen["screen_id"] == "budget_ask" and gesture == "press":
        await show_consent()  # back, nothing changed
    elif S.screen["screen_id"] == "budget_confirm" and gesture in ("press", "swipe_down"):
        if gesture == "press" and S.budget_draft:  # confirmed: this budget, then the flights under it
            S.proposal, S.budget_draft = S.budget_draft, None
            await publish("budget.proposed", S.proposal)
            await accept_limit("glasses")
            await offer_choices()
        else:  # roll back to the budget that was proposed
            S.budget_draft = None
            await publish("budget.rolled_back", {"limit_usd": S.proposal["limit_usd"] if S.proposal else None})
            await show_consent()
    elif gesture == "press" and stage in ("ready", "resolved") and S.screen["screen_id"] == "ready":
        await start_flow("glasses")
    elif gesture == "press" and stage == "resolved" and S.claim_drafting and not S.claim:
        # Tapped past the outcome while the claim is being drafted: go to it, never drop it.
        if S.claim_rush:
            S.claim_rush.set()
        await show("claim_drafting", ["Getting money back", "Checking your benefits"], {})
    elif gesture == "press" and stage == "resolved":
        await show("idle", [], {})
        S.reset()
        await show_ready()
        refresh_live_flight()
    elif gesture == "press" and stage == "cancelled":
        if S.proposal:  # yes to the spending limit (or "fix it" again after a no)
            await accept_limit("glasses")
            await offer_choices()
        else:
            await offer_pick()
    elif gesture == "swipe_down" and stage == "cancelled" and S.screen["screen_id"] == "cancelled":
        await publish("mandate.declined", {"limit_usd": S.proposal["limit_usd"] if S.proposal else None})
        await show("declined", ["OK, nothing spent", "Tap = fix it"], {"press": "fix"})
    elif stage == "offer" and gesture == "swipe_down" and S.screen["screen_id"] == "flight_list":
        await next_choice()
    elif stage == "offer" and gesture == "select" and S.screen["screen_id"] == "flight_list":
        if g.index is None or not 0 <= g.index < len(S.choices):
            return {"handled": False, "stage": stage, "reason": f"no row {g.index}"}
        await select_choice(g.index)
    elif (stage == "offer" and gesture == "hold" and S.screen["screen_id"] == "flight_list"
          and g.index is not None and g.index != S.cursor):
        # The glasses approved a different row than the one this approval is for: book nothing.
        return {"handled": False, "stage": stage,
                "reason": f"selection mismatch: glasses row {g.index}, engine row {S.cursor}"}
    elif stage in ("offer", "fee") and gesture in ("hold", "swipe_down"):
        a = pending("booking" if stage == "offer" else "fee")
        if not a:
            return {"handled": False, "stage": stage}
        if stage == "offer" and gesture == "swipe_down":
            await show("only_option", ["Only option tonight", fit(f"{S.pick['airline']} {hhmm(S.pick['departs'])}", f"{S.pick['flight']} {hhmm(S.pick['departs'])}"), "Hold to book"],
                       {"hold": "approve"})
        else:
            await answer(a["approval_id"], gesture == "hold", "glasses")
    else:
        return {"handled": False, "stage": stage}
    return {"handled": True, "stage": S.stage}


class Ask(BaseModel):
    question: str = ""
    audio: str | None = None  # base64 WAV from the glasses mic (push-to-talk); used when question is empty
    format: str = "wav"
    show: bool = True  # put the short answer on the glasses


ANSWER_S = 10


async def restore_screen(prev: dict, after_s: float = 0) -> None:
    """Put back what the glasses showed before an answer, unless something newer replaced it."""
    await asyncio.sleep(after_s)
    if S.screen["screen_id"] == "answer":
        S.screen = prev
        await publish("hud.screen", S.screen)


@app.post("/ask")
async def ask(q: Ask):
    """A free question to the agent: flight status, vault, spending, what it's doing. Read-only tools:
    it never books, pays or calls. The short answer goes on the glasses unless a spend is waiting."""
    if not agent.can_ask():
        raise HTTPException(503, "needs ANTHROPIC_API_KEY")
    question = q.question.strip()[:500]
    if not question and q.audio:
        if len(q.audio) > voice.MAX_AUDIO_BYTES * 4 // 3:
            raise HTTPException(413, "audio too long")
        try:
            question = (await voice.transcribe(q.audio, q.format, language=None))[:500]  # any language
        except Exception as e:  # noqa: BLE001 - say why on the glasses instead of hanging
            raise HTTPException(502, str(e)[:200])
        if not question:
            raise HTTPException(422, "didn't catch that")
    if not question:
        raise HTTPException(400, "empty question")

    async def read_ledger(_: dict) -> dict:
        return S.ledger.view(S.mandate)

    async def read_task(_: dict) -> dict:
        return {"stage": S.stage, "task_id": S.task_id, "pick": S.pick and brief(S.pick), "outcome": S.outcome,
                "trip_claim": S.claim and {k: S.claim[k] for k in ("status", "total_usd", "items", "program")},
                "glasses_show": S.screen["lines"]}

    first = len(S.agent_log)
    b = booking()
    facts = {"question": question, "traveler": MOCK["traveler"]["name"],
             "now": datetime.now(LA).isoformat(timespec="minutes"),
             "travelers_flight": {k: b[k] for k in ("airline", "flight", "from", "to", "date", "departs")},
             "trip_state": "no disruption yet" if S.task_id is None else S.stage,
             "vault": (await read_vault())["items"]}  # small; saves the tool round trip Claude always made
    if b.get("live") and S.task_id is None and status.enabled():
        # The usual question is about their own flight: hand Claude its live status up front (cached 60 s),
        # which saves a whole tool round trip on the glasses.
        facts["travelers_flight_live_status"] = await trip_live_status()
    try:
        out = json.loads(await agent.run("ask", facts, {
            "read_vault": read_vault, "check_flight_status": lambda i: flight_status(i["flight"]),
            "read_ledger": read_ledger, "read_task": read_task}, agent_step, model=agent.ASK_MODEL))
    except (anthropic.APIError, RuntimeError, TimeoutError, ValueError, KeyError) as e:
        await publish("agent.failed", {"phase": "ask", "error": str(e)[:300]})
        raise HTTPException(502, f"agent failed: {e}"[:300])
    lines = [line[:24] for line in out["glasses"][:3]] or ["No answer"]
    await publish("agent.answer", {"question": question, "answer": out["answer"], "glasses": lines})
    shown = q.show and S.stage not in ("offer", "fee")  # never cover a screen that's waiting for a gesture
    if shown:
        prev = S.screen if S.screen["screen_id"] != "answer" else S.before_answer
        S.before_answer = prev
        # In free mode a long press asks again (push-to-talk on the glasses).
        await show("answer", lines, {"press": "dismiss", **({"hold": "ask"} if S.stage == "ready" else {})}, ANSWER_S)
        run_later(restore_screen(prev, ANSWER_S))
    return {"question": question, "answer": out["answer"], "glasses": lines, "shown": shown,
            "steps": S.agent_log[first:]}


class VoiceInput(BaseModel):
    screen_id: str
    audio: str | None = None  # base64 WAV, 16 kHz mono (what the G2 mic gives)
    format: str = "wav"
    transcript: str | None = None  # skip speech-to-text: typed commands and tests


@app.post("/voice")
async def voice_(v: VoiceInput):
    """Voice command from the glasses: transcribe, pick an intent the current screen allows, then run it
    through the same path as a gesture. An approval of a spend is never applied by voice: it returns
    confirm_required and the wearer taps to confirm (the spend still goes through policy.py)."""
    def reply(**kw) -> dict:
        base = {"transcript": "", "intent": "unknown", "confidence": 0.0, "via": "none", "model": None,
                "gesture": None, "handled": False, "confirm_required": False, "reason": None, "stage": S.stage}
        return {**base, **kw}

    if v.screen_id != S.screen["screen_id"]:  # check before paying for speech-to-text
        return reply(reason=f"stale screen: {v.screen_id}, now {S.screen['screen_id']}")
    if not voice.intents_for(v.screen_id):
        return reply(reason=f"no voice commands on {v.screen_id}")
    if v.transcript is not None:
        transcript = v.transcript.strip()
    elif v.audio:
        if len(v.audio) > voice.MAX_AUDIO_BYTES * 4 // 3:
            return reply(reason="audio too long")
        try:
            transcript = await voice.transcribe(v.audio, v.format)
        except Exception as e:  # keep the glasses responsive; the wearer can still tap
            return reply(reason=str(e)[:200])
    else:
        return reply(reason="no audio")

    if v.screen_id == "flight_list" and S.choices:
        # Pick a flight by voice (Ollama): the glasses move the selection to that row and ask for a tap.
        # Nothing changes here; the booking still needs the tap (`hold` with the row) and policy.py.
        row, confidence, via, model, note = await voice.choose_flight(transcript, S.choices, S.cursor)
        await publish("voice.heard", {"screen_id": v.screen_id, "transcript": transcript,
                                      "intent": "choose" if row is not None else "unknown", "index": row,
                                      "confidence": confidence, "via": via, "model": model, "note": note})
        result = reply(transcript=transcript, confidence=confidence, via=via, model=model)
        if row is None:
            failed = note and note.startswith("ollama failed")
            return {**result, "reason": note if failed else "didn't match a flight on this screen"}
        return {**result, "intent": "choose", "index": row, "gesture": "hold", "confirm_required": True,
                "reason": "spend approvals need a tap" + (f" ({note})" if note else "")}
    intent, confidence, via, model, note = await voice.classify(transcript, v.screen_id, S.screen["lines"])
    gesture = voice.intents_for(v.screen_id).get(intent)
    await publish("voice.heard", {"screen_id": v.screen_id, "transcript": transcript, "intent": intent,
                                  "confidence": confidence, "via": via, "model": model, "note": note})
    result = reply(transcript=transcript, intent=intent, confidence=confidence, via=via, gesture=gesture,
                   model=model)
    if not gesture:
        # A model failure must read as a failure ("intent model failed: …"), never as "didn't understand".
        failed = note and (note.startswith("intent model failed") or note.startswith("voice not configured"))
        return {**result, "reason": note if failed else "didn't match a command on this screen"}
    if voice.needs_tap(v.screen_id, intent):
        return {**result, "confirm_required": True, "reason": "spend approvals need a tap"}
    if intent == "budget" and not S.proposal:  # "Not booked" reuses `cancelled` without a budget to change
        return {**result, "intent": "unknown", "gesture": None, "reason": "no budget to change on this screen"}
    if intent == "budget":  # "make it 450" → confirm it with a tap; "change the budget" → ask for the amount
        amount = voice.parse_amount(transcript)
        if amount:
            await confirm_budget(amount)
        else:
            await ask_budget()
        return {**result, "gesture": None, "handled": True, "stage": S.stage,
                "reason": f"budget ${amount:g}: tap to confirm" if amount else "say an amount"}
    if voice.is_local(v.screen_id, intent):  # hide / show the call: the glasses do it, nothing changes here
        return {**result, "gesture": None, "handled": True, "reason": "local"}
    # The screen may have changed while we were transcribing; /input checks screen_id again.
    r = await input_(Gesture(gesture=gesture, screen_id=v.screen_id))
    return {**result, "handled": r["handled"], "stage": r["stage"], "reason": r.get("reason")}


@app.post("/simulate/cancel")
async def simulate_cancel():
    if S.stage not in ("ready", "resolved"):
        return {"handled": False, "stage": S.stage}
    await start_flow("simulate")
    return {"handled": True, "task_id": S.task_id}


@app.post("/demo/reset")
async def demo_reset():
    S.reset()
    await publish("demo.reset", {})
    await show_ready()
    refresh_live_flight()
    return {"ok": True}


@app.on_event("startup")
async def find_live_flight() -> None:
    refresh_live_flight(force=True)


@app.get("/state")
def state():
    return snapshot()


# ---------- ASI:One path (orchestrator agent) ----------

class TaskStart(BaseModel):
    source: str = "asi1"


@app.post("/tasks")
async def tasks_start(body: TaskStart):
    if S.stage not in ("ready", "resolved"):
        await demo_reset()
    await start_flow(body.source)
    a = await offer_pick()
    return {"task_id": S.task_id, "stage": S.stage, "options": S.options, "pick": S.pick,
            "approval_id": a["approval_id"] if a else None}


@app.get("/tasks/{task_id}")
def tasks_get(task_id: str):
    if task_id != S.task_id:
        raise HTTPException(404, f"unknown task {task_id}")
    return snapshot()


class ApprovalBody(BaseModel):
    approval_id: str | None = None
    task_id: str | None = None
    approved: bool
    fee_allowance_usd: float | None = None


@app.post("/approval")
async def approval(body: ApprovalBody):
    if body.fee_allowance_usd is not None:
        S.fee_allowance = body.fee_allowance_usd
    a = S.approvals.get(body.approval_id) if body.approval_id else pending()
    if not a:
        raise HTTPException(404, "no pending approval")
    return await answer(a["approval_id"], body.approved, "asi1" if body.fee_allowance_usd is not None else "api")


# ---------- voice agent tools ----------

class SpendRequest(BaseModel):
    amount: float
    reason: str = "fee"
    kind: str = "fee"
    merchant: str | None = None
    mcc: str | None = None


@app.post("/call/approval")
async def call_approval(r: SpendRequest):
    """Voice tool request_approval. Returns at once; poll GET /call/approval/{id}."""
    a = await request_fee(r.amount, r.reason, r.merchant, r.mcc)
    return {"approval_id": a["approval_id"], "status": a["status"]}


@app.get("/call/approval/{approval_id}")
async def call_approval_status(approval_id: str, wait_s: float = 0):
    """Voice tool check_approval. With wait_s, holds the request until the wearer answers
    or time runs out (capped at 12 s), since the voice agent can't sleep between checks."""
    a = S.approvals.get(approval_id)
    if not a:
        raise HTTPException(404, f"no approval {approval_id}")
    loop = asyncio.get_running_loop()
    end = loop.time() + max(0.0, min(wait_s, 12.0))
    while a["status"] == "pending" and loop.time() < end:
        await asyncio.sleep(0.25)
    return {"approval_id": approval_id, "status": a["status"]}


class CallOutcome(BaseModel):
    held: bool
    door_code: str | None = None
    contact: str | None = None
    fee_usd: float | None = None
    transcript_url: str | None = None
    verified: bool = False
    transcript: str | None = None  # "Agent: ...\nClerk: ..."; when present, Claude checks the outcome


@app.post("/call/completed")
async def call_completed(o: CallOutcome):
    outcome = o.model_dump(exclude={"transcript_url", "transcript"})
    if o.transcript:
        outcome = await verify.check_call(o.transcript, outcome)
    await finish_call(outcome, o.transcript_url, o.transcript)
    return {"ok": True, "outcome": outcome}


@app.post("/call/webhook")
async def call_webhook(request: Request):
    """ElevenLabs post-call webhook. Verifies the HMAC signature, then checks the transcript
    with Claude in the background (ElevenLabs only needs a fast 200)."""
    raw = await request.body()
    if not call.signature_ok(raw, request.headers.get("elevenlabs-signature"), os.getenv("ELEVENLABS_WEBHOOK_SECRET")):
        raise HTTPException(401, "invalid or missing ElevenLabs signature")
    event = json.loads(raw)
    data = event.get("data") or {}
    task_id = ((data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}).get("task_id")
    if task_id != S.task_id:
        return {"ok": True, "ignored": "call from another task"}  # e.g. a call from before a demo reset
    if event.get("type") == "post_call_transcription":
        transcript = call.transcript_text(data.get("transcript") or [])

        async def check_and_finish():
            await finish_call(await verify.check_call(transcript, call.reported_outcome(data)), None, transcript)
        run_later(check_and_finish())
    elif event.get("type") == "call_initiation_failure":
        run_later(call_failed("the call did not connect"))
    return {"ok": True}


# ---------- payments and mandate ----------

class PaymentRequest(BaseModel):
    merchant: str
    amount: float
    mcc: str


@app.post("/merchant/payment-request")
async def merchant_payment(p: PaymentRequest):
    # An approved spend is already checked and in the ledger (pay()); the merchant may charge it once.
    covered = next((a for a in S.approvals.values() if a["status"] == "approved" and not a.get("charged")
                    and a["merchant"] == p.merchant and a["amount"] == p.amount and a["mcc"] == p.mcc), None)
    if covered:
        covered["charged"] = True
        return {"paid": True, "token_id": S.mandate.token_id, "reason": f"covered by {covered['approval_id']}"}
    decision, why, _ = policy.check_spend(S.mandate, S.ledger, p.amount, p.mcc)
    if decision != "allow":
        why = why if decision == "deny" else "needs the wearer's approval first"
        S.ledger.denied.append({"amount": p.amount, "merchant": p.merchant, "reason": why, "ts": now()})
        raise HTTPException(403, why)
    await pay({"amount": p.amount, "merchant": p.merchant, "mcc": p.mcc, "kind": "merchant"})
    return {"paid": True, "token_id": S.mandate.token_id, "reason": why}


@app.get(tap.DIRECTORY_PATH)
def tap_key_directory():
    """Public key merchants use to check the agent's signed payment requests."""
    return tap.directory()


@app.get("/claim")
async def get_claim(wait_s: float = 0):
    """The trip's travel-benefit claim for the orchestrator and dashboard. It's drafted a few seconds after the
    trip resolves; with wait_s, holds the request until it's ready or time runs out (capped at 15 s)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + max(0.0, min(wait_s, 15.0))
    while not S.claim and S.claim_drafting and loop.time() < end:
        await asyncio.sleep(0.25)
    return {"claim": S.claim, "drafting": S.claim_drafting and not S.claim, "task_id": S.task_id, "stage": S.stage}


class ClaimSubmit(BaseModel):
    claim_id: str | None = None  # guards against submitting a different trip's claim
    via: str = "asi1"


@app.post("/claim/submit")
async def post_claim_submit(body: ClaimSubmit):
    """Submit the ready claim, the same as a tap on the glasses. Idempotent: a second call returns it as is."""
    if not S.claim:
        raise HTTPException(404, "no claim yet" + (" (drafting)" if S.claim_drafting else ""))
    if body.claim_id and body.claim_id != S.claim["claim_id"]:
        raise HTTPException(409, f"claim {body.claim_id} is not the current one ({S.claim['claim_id']})")
    await submit_claim(body.via[:20])
    return {"claim": S.claim, "ledger": S.ledger.view(S.mandate)}


@app.get("/vault")
def vault():
    """The traveler's documents: pre-seeded ones plus what the agent saved during the flow."""
    return {"items": S.vault}


@app.get("/ledger")
def ledger():
    return S.ledger.view(S.mandate)


@app.post("/mandate")
def set_mandate(fields: dict):
    S.mandate = policy.Mandate.from_dict({**MOCK["mandate"], **fields})
    return S.mandate.as_dict()


@app.get("/flights/search")
async def flights_search():
    options, source, error = await find_options(booking()["from"], booking()["to"])
    return {"options": policy.rank_options(options, S.mandate, S.ledger, MOCK["deadline"]),
            "source": source, "error": error}


@app.get("/tests")
def tests():
    """Last `python test_engine.py` run, for the dashboard's pass-rate panel."""
    results = Path(__file__).resolve().parents[1] / "test-results.json"
    if not results.exists():
        raise HTTPException(404, "no test run yet; run python test_engine.py in engine/")
    return json.loads(results.read_text())


@app.get("/")
def dashboard():
    return FileResponse(DASHBOARD)


# The dashboard's other files, e.g. the recorded-call fallback at /dashboard/recorded-call.mp3.
app.mount("/dashboard", StaticFiles(directory=DASHBOARD.parent), name="dashboard")
