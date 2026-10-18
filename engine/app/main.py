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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import call, policy, tap, verify
from .call import start_call

ROOT = Path(__file__).resolve().parents[2]
MOCK = json.loads((ROOT / "contract" / "mock-data.json").read_text())
DASHBOARD = ROOT / "dashboard" / "index.html"
CALL_MODE = os.getenv("CALL_MODE", "mock")  # mock | elevenlabs
HEARTBEAT_S = 15
MOCK_CLERK_DELAY_S = float(os.getenv("MOCK_CLERK_DELAY_S", "4"))  # clerk asks for the fee
MOCK_CALL_END_S = float(os.getenv("MOCK_CALL_END_S", "2"))  # call wraps up after the answer

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
        self.pick: dict | None = None
        self.approvals: dict[str, dict] = {}
        self.fee_allowance = 0.0
        self.outcome: dict | None = None
        self.screen: dict = ready_screen()
        self.vault: list[dict] = seed_vault()


def seed_vault() -> list[dict]:
    """What the traveler saved before the trip (pre-seeded, per the SPEC). The flow adds to it."""
    b, lodging = MOCK["booking"], MOCK["lodging"]
    return [
        {"id": "vlt-ua183", "type": "boarding_pass", "title": f"{b['airline']} {b['flight']} {b['from']}-{b['to']}",
         "saved_at": None, "source": "traveler",
         "data": {k: b[k] for k in ("airline", "flight", "from", "to", "date", "departs", "pnr")}},
        {"id": "vlt-lodging", "type": "lodging_confirmation", "title": lodging["name"],
         "saved_at": None, "source": "traveler",
         "data": {"name": lodging["name"], "confirmation": lodging["confirmation"],
                  "desk_closes": lodging["desk_closes"], "note": lodging["note"]}},
    ]


async def save_to_vault(type_: str, title: str, data: dict) -> dict:
    item = {"id": f"vlt-{uuid.uuid4().hex[:8]}", "type": type_, "title": title,
            "saved_at": now(), "source": "agent", "data": data}
    S.vault.append(item)
    await publish("vault.updated", {"type": type_, "id": item["id"], "title": title})
    return item


def ready_screen() -> dict:
    return {"screen_id": "ready", "lines": ["Ready", "Tap to start"], "gestures": {"press": "start"}, "clear_after_s": None}


S = State()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        "call_mode": CALL_MODE,
    }


# ---------- the flow ----------

async def start_flow(source: str) -> None:
    S.task_id = f"task-{uuid.uuid4().hex[:8]}"
    S.stage = "cancelled"
    b, offer = MOCK["booking"], MOCK["airline_offer"]
    await publish("flight.cancelled", {"flight": b["flight"], "route": f"{b['from']}-{b['to']}",
                                       "airline_offer": offer, "source": source})
    S.options = policy.rank_options(MOCK["options"], S.mandate, S.ledger, MOCK["deadline"])
    S.pick = next((o for o in S.options if o["verdict"] == "pick"), None)
    await publish("options.ranked", {"options": S.options})
    await show("cancelled", [f"{b['flight']} cancelled", f"{offer['airline']}: {hhmm(offer['departs'])} tmrw", "Tap = fix it"],
               {"press": "fix"})


async def offer_pick() -> dict | None:
    p = S.pick
    if not p:
        await show("no_option", ["No flight tonight", "fits your budget"], {}, 10)
        return None
    S.stage = "offer"
    return await request_spend(
        "booking", p["price_usd"], p["airline"], p["mcc"], f"{p['airline']} {p['flight']} tonight",
        screen=("booking_offer",
                [f"{p['airline']} tonight {hhmm(p['departs'])}", f"${p['price_usd']} · lands {hhmm(p['arrives'], False)}", "Hold to book"],
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


async def after_booking() -> None:
    p, offer, lodging = S.pick, MOCK["airline_offer"], MOCK["lodging"]
    S.stage = "booked"
    refund = MOCK["refund"]
    S.ledger.refunds.append({"amount": refund["amount_usd"], "airline": refund["airline"], "rule": refund["rule"],
                             "status": "pending", "ts": now()})
    await publish("offer.declined", {"airline": offer["airline"], "flight": offer["flight"],
                                     "refund_usd": refund["amount_usd"], "status": "pending"})
    paid = next((s for s in reversed(S.ledger.spends) if s["kind"] == "booking"), {})
    b = MOCK["booking"]
    await save_to_vault("boarding_pass", f"{p['airline']} {p['flight']} {b['from']}-{b['to']}", {
        "airline": p["airline"], "flight": p["flight"], "from": b["from"], "to": b["to"], "date": b["date"],
        "departs": p["departs"], "arrives": p["arrives"], "price_usd": p["price_usd"],
        "payment_reference": paid.get("reference"), "replaces": b["flight"]})
    await show("booked", ["Booked · pass saved"])
    await asyncio.sleep(1.5)
    eta = policy.arrival_eta(p["arrives"], lodging["travel_minutes_from_airport"])
    await publish("cutoff.detected", {"place": lodging["name"], "closes_at": lodging["desk_closes"],
                                      "arrival": p["arrives"], "eta": eta})
    await show("calling", [f"Desk closes {hhmm(lodging['desk_closes'])}", f"You land {hhmm(p['arrives'], False)}",
                           "Calling guesthouse"])
    S.stage = "calling"
    variables = {"guest_name": MOCK["traveler"]["name"], "confirmation": lodging["confirmation"],
                 "eta": hhmm(eta), "task_id": S.task_id}
    await publish("call.started", {"to": lodging["name"], "purpose": "hold the room for a late arrival", "mode": CALL_MODE})
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
    await show("call_failed", ["Call didn't connect", "Details on your phone"], {"press": "dismiss"}, 10)


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
    await show(screen_id, lines, {"press": "dismiss"}, 10)


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
    gesture: str  # press | hold | swipe_down
    screen_id: str | None = None


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
    if gesture == "press" and stage in ("ready", "resolved") and S.screen["screen_id"] == "ready":
        await start_flow("glasses")
    elif gesture == "press" and stage == "resolved":
        await show("idle", [], {})
        S.reset()
        await show("ready", ["Ready", "Tap to start"], {"press": "start"})
    elif gesture == "press" and stage == "cancelled":
        await offer_pick()
    elif stage in ("offer", "fee") and gesture in ("hold", "swipe_down"):
        a = pending("booking" if stage == "offer" else "fee")
        if not a:
            return {"handled": False, "stage": stage}
        if stage == "offer" and gesture == "swipe_down":
            await show("only_option", ["Only option tonight", f"{S.pick['airline']} {hhmm(S.pick['departs'])}", "Hold to book"],
                       {"hold": "approve"})
        else:
            await answer(a["approval_id"], gesture == "hold", "glasses")
    else:
        return {"handled": False, "stage": stage}
    return {"handled": True, "stage": S.stage}


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
    await show("ready", ["Ready", "Tap to start"], {"press": "start"})
    return {"ok": True}


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
def flights_search():
    return {"options": policy.rank_options(MOCK["options"], S.mandate, S.ledger, MOCK["deadline"])}


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
