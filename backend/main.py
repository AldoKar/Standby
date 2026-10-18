import asyncio
import copy
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.append(str(Path(__file__).resolve().parent.parent))
from contracts.events import (AcceptAlertBody, AgentTask, ApprovalBody, Envelope, FlightCancelled,
                              Option, PayBody, PayResult, SearchResult, make_event)

import flight_status
import guardrails

AGENT_URL = os.getenv("AGENT_URL")  # Handle It Agent REST endpoint; unset = agent not wired yet
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "120"))  # each AeroAPI call costs credit; don't go lower
USER_ID = "demo_user"

app = FastAPI(title="Handle It backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ponytail: in-memory state, lost on restart; fine for the demo, move to Supabase with the Vault
INITIAL = {
    "booking": {"flight": "UA183", "airline": "United", "origin": "LAX", "dest": "SFO",
                "date": "2026-10-18", "departure": "18:10", "arrival": "19:35",
                "gate": "52", "pnr": "ABC123", "price": 189},
    "status": "ON_TIME",
}
state = copy.deepcopy(INITIAL)
listeners: set[asyncio.Queue] = set()

MOCK_FLIGHTS = [
    Option(flight="UA183", airline="United", origin="LAX", dest="SFO", departure="18:10", arrival="19:35", price=189, refundable=True),
    Option(flight="DL412", airline="Delta", origin="LAX", dest="SFO", departure="19:00", arrival="20:20", price=340, refundable=True),
    Option(flight="AS1098", airline="Alaska", origin="LAX", dest="SFO", departure="21:30", arrival="22:55", price=165, refundable=False),
    Option(flight="UA927", airline="United", origin="LAX", dest="SFO", departure="19:15", arrival="20:40", price=215, refundable=True),
]


def publish(event: Envelope) -> Envelope:
    for q in listeners:
        q.put_nowait(event)
    return event


def search(origin: str, dest: str) -> list[Option]:
    # ponytail: mock data; swap this one function for a real flights API in "real mode"
    return [o for o in MOCK_FLIGHTS
            if o.origin == origin and o.dest == dest
            and not (o.flight == state["booking"]["flight"] and state["status"] == "CANCELLED")]


async def send_to_agent(task: AgentTask) -> None:
    if not AGENT_URL:
        print(f"[agent not wired] would send {task.model_dump()}")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{AGENT_URL}/task", json=task.model_dump())


@app.get("/health")
def health():
    return {"ok": True, "listeners": len(listeners), "agent_wired": bool(AGENT_URL)}


@app.get("/events")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    listeners.add(q)

    async def gen():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {event.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keeps phone/proxy connections from timing out
        finally:
            listeners.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/events")
def post_event(event: Envelope):
    return publish(event)


@app.get("/flights/search", response_model=SearchResult)
def flights_search(origin: str, dest: str, deadline: str | None = None, max_price: float | None = None):
    # Returns every flight on the route; the agent decides and explains rejections.
    return SearchResult(options=search(origin, dest))


@app.post("/approval")
def approval(body: ApprovalBody):
    guardrails.approvals[body.task_id] = body.approved
    kind = "approval.granted" if body.approved else "approval.rejected"
    return publish(make_event(kind, {}, task_id=body.task_id))


@app.post("/pay", response_model=PayResult)
def pay(body: PayBody):
    try:
        guardrails.check_payment(body.task_id, body.amount)
    except guardrails.GuardrailError as e:
        raise HTTPException(403, str(e))
    guardrails.consume_approval(body.task_id)
    # ponytail: simulated charge; call Visa sandbox here once we have keys
    return PayResult(reference=f"VISA-{uuid4().hex[:8].upper()}")


@app.post("/accept-alert")
async def accept_alert(body: AcceptAlertBody, background: BackgroundTasks):
    task = AgentTask(task_id=body.task_id or f"task_{uuid4().hex[:8]}", kind="resolve",
                     user_id=USER_ID, input={"booking": state["booking"]})
    background.add_task(send_to_agent, task)
    return {"task_id": task.task_id}


@app.get("/flights/status")
async def get_flight_status(flight: str):
    try:
        status = await flight_status.fetch_status(flight)
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(502, f"flight status unavailable: {e}")
    if not status:
        raise HTTPException(404, f"no flight found for {flight}")
    return status


@app.post("/flights/status/show")
async def show_flight_status(flight: str | None = None):
    """'What's my flight status?' -> publishes flight.status so the HUD shows it.
    No flight given: the tracked one, else the booked one."""
    status = await get_flight_status(flight or tracking["flight"] or state["booking"]["flight"])
    publish(make_event("flight.status", status))
    return status


# ponytail: one tracked flight for the whole app; per-user tracking when there are real users
tracking = {"flight": None, "last": None, "task": None}


async def track_loop():
    while tracking["flight"]:
        try:
            new = await flight_status.fetch_status(tracking["flight"])
        except Exception as e:  # network/API hiccup: keep tracking, try again next round
            print(f"[track] {tracking['flight']}: {e}")
            new = None
        if new:
            for kind, data in flight_status.diff(tracking["last"], new):
                publish(make_event(kind, data))
            tracking["last"] = new
            if new["cancelled"] or (new["status"] or "").startswith("Arrived"):
                break  # nothing more to watch; saves API credit
        await asyncio.sleep(POLL_SECONDS)


@app.post("/track")
async def track(flight: str):
    """Start following a real flight (e.g. UA183 or UAL183). Changes are published to /events."""
    status = await get_flight_status(flight)
    tracking.update(flight=flight, last=status)
    publish(make_event("flight.status", status))
    if not tracking["task"] or tracking["task"].done():
        tracking["task"] = asyncio.create_task(track_loop())
    return status


@app.delete("/track")
def untrack():
    tracking.update(flight=None, last=None)
    return {"ok": True}


@app.post("/simulate/flight")
def simulate_flight(changes: dict):
    """Fake mode only (no AEROAPI_KEY): e.g. {"gate": "61"}, {"delay_min": 30, "departure": "18:40"}, {"cancelled": true}."""
    flight_status.FAKE.update({k: v for k, v in changes.items() if k in flight_status.FAKE})
    return flight_status.FAKE


@app.post("/simulate/cancel")
def simulate_cancel():
    state["status"] = "CANCELLED"
    b = state["booking"]
    return publish(make_event("flight.cancelled",
                              FlightCancelled(flight=b["flight"], route=f"{b['origin']}-{b['dest']}")))


@app.post("/demo/reset")
def demo_reset():
    state.clear()
    state.update(copy.deepcopy(INITIAL))
    guardrails.approvals.clear()
    return {"ok": True, "state": state}
