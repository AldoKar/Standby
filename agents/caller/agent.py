"""Standby Caller: places disclosed AI calls to businesses that have no API (owner: P2).

Usable on its own in ASI:One ("call this guesthouse and hold my room"), and hired by the
Standby orchestrator. Charges $1.99 per call over the Agent Payment Protocol: the caller
is the seller, the orchestrator is the buyer.

    orchestrator                              caller
      --- ChatMessage: the job -------------->
      <-- RequestPayment $1.99 ---------------
      --- CommitPayment(transaction_id) ----->
      <-- CompletePayment -------------------  then places the call
      <-- ChatMessage: structured outcome ---

Settlement is simulated: the handshake is the real protocol, but no FET moves, because
these agents hold no funds. See agents/README.md for what making it real would take.

Rules that are not negotiable, from docs/SPEC.md: business lines only, the first sentence
says it is an AI and that the call is recorded, and it never phones or pays the airline
that cancelled.

Run from agents/:  python caller/agent.py
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8000").rstrip("/")
PRICE_USD = os.getenv("CALL_PRICE_USD", "1.99")
PAYMENT_METHOD = os.getenv("CALL_PAYMENT_METHOD", "fet_direct")  # 0.1.0 has no Stripe rail
PAYMENT_CURRENCY = os.getenv("CALL_PAYMENT_CURRENCY", "USD")
PAYMENT_DEADLINE_S = 120
# Force the first attempt to voicemail so the retry path can be demonstrated on cue.
VOICEMAIL_FIRST = os.getenv("CALL_VOICEMAIL_FIRST", "").lower() in ("1", "true", "yes")
RING_S = float(os.getenv("CALL_RING_SECONDS", "2"))

MOCK = json.loads((ROOT / "contract" / "mock-data.json").read_text())

# Reachability: mailbox only, and `endpoint=` must never be passed alongside it.
# uagents/config.py:75-99 takes the endpoint and drops the mailbox when both are given,
# so `is_mailbox_agent` goes False, no MailboxClient is ever started, and the agent
# registers as type "custom" instead of "mailbox" — which is also why the Agentverse
# inspector would not offer to create a mailbox for it. Worse, the Almanac record is
# global and last-writer-wins: one run with a loopback endpoint publishes
# http://127.0.0.1:8002 as this agent's only public address, so every sender — ASI:One
# included — is told to deliver to its own machine. That failure is invisible from here.
# To reach a locally-run Caller, the sender takes the shortcut instead: see
# CALLER_LOCAL_ENDPOINT in orchestrator/agent.py.
CALLER_PORT = int(os.getenv("CALLER_PORT", "8002"))

CALLER_SEED = os.getenv("CALLER_SEED")
if not CALLER_SEED:
    raise SystemExit("CALLER_SEED is not set. Put one in .env (any high-entropy string).")

http = httpx.AsyncClient(base_url=ENGINE_URL, timeout=20.0)

agent = Agent(
    name="standby-caller",
    seed=CALLER_SEED,
    port=CALLER_PORT,
    mailbox=True,  # never add endpoint= here; see the note above CALLER_PORT
    publish_agent_details=True,
    description=(
        "Phones businesses that have no API and reports back what was agreed. Says it is "
        "an AI in its first sentence, calls business lines only, retries once on "
        "voicemail. $1.99 per call through the Agent Payment Protocol."
    ),
    readme_path=str(Path(__file__).with_name("README.md")),
)

chat_proto = Protocol(spec=chat_protocol_spec)
pay_proto = Protocol(spec=payment_protocol_spec, role="seller")


# ---------- jobs ----------

def parse_job(text: str) -> dict:
    """A job arrives as JSON from the orchestrator, or as plain English from a person."""
    try:
        job = json.loads(text)
        if isinstance(job, dict):
            return {
                "task_id": job.get("task_id"),
                "purpose": job.get("purpose") or "hold the room for a late arrival",
                "to": job.get("to") or MOCK["lodging"]["name"],
            }
    except (ValueError, TypeError):
        pass
    return {"task_id": None, "purpose": text.strip(), "to": MOCK["lodging"]["name"]}


def disclosure(job: dict) -> str:
    traveller = MOCK["traveller"]["name"] if "traveller" in MOCK else MOCK["traveler"]["name"]
    return (
        f"Hi, I'm an AI assistant calling for {traveller}, confirmation "
        f"{MOCK['lodging']['confirmation']}; this call is recorded."
    )


async def place_call(ctx: Context, job: dict, attempt: int) -> dict:
    """One attempt. Prefers the engine's call endpoint; falls back to the mock clerk.

    contract/api.md has no agent-facing way to start a call (see agents/NEEDS.md), so the
    engine endpoint is tried first and the mock stands in until P1 adds it.
    """
    ctx.logger.info(f"attempt {attempt}: calling {job['to']} to {job['purpose']}")
    try:
        r = await http.post("/call/start", json={"task_id": job.get("task_id"),
                                                 "purpose": job["purpose"], "to": job["to"]})
        if r.status_code < 400:
            return await watch_engine_call(ctx, job)
    except httpx.HTTPError:
        pass
    return await mock_call(ctx, job, attempt)


async def watch_engine_call(ctx: Context, job: dict) -> dict:
    """The engine is placing a real call; wait for it to report the outcome."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 90
    while loop.time() < deadline:
        await asyncio.sleep(2)
        try:
            snap = (await http.get(f"/tasks/{job['task_id']}")).json()
        except (httpx.HTTPError, ValueError):
            continue
        if snap.get("stage") == "resolved" and snap.get("outcome"):
            return dict(snap["outcome"], mode="engine")
    return {"held": False, "verified": False, "mode": "engine",
            "issues": ["the call did not report back in time"]}


async def mock_call(ctx: Context, job: dict, attempt: int) -> dict:
    """Stands in for the phone call so the flow is demonstrable without Twilio."""
    await asyncio.sleep(RING_S)
    if VOICEMAIL_FIRST and attempt == 1:
        ctx.logger.info("no answer — voicemail")
        return {"held": False, "verified": False, "voicemail": True, "mode": "mock"}

    script = MOCK["call_script_mock"]
    outcome = {
        # Echo what was asked, so the caller cannot look like it answered a different
        # question. The mock clerk agrees to whatever the job was.
        "asked": job["purpose"],
        "agreed": True,
        "held": True,
        "fee_usd": script["fee_usd"],
        "door_code": script["door_code"],
        "contact": script["contact"],
        "verified": True,
        "mode": "mock",
    }
    # Tell the engine, but only when it is actually waiting on a call, so a standalone
    # call can never finish somebody else's task.
    if job.get("task_id"):
        try:
            snap = (await http.get(f"/tasks/{job['task_id']}")).json()
            if snap.get("stage") in ("calling", "fee"):
                await http.post("/call/completed", json={k: v for k, v in outcome.items()
                                                         if k in ("held", "door_code", "contact",
                                                                  "fee_usd", "verified")})
        except (httpx.HTTPError, ValueError):
            ctx.logger.info("engine not reachable; reporting the outcome to the buyer only")
    return outcome


async def run_job(ctx: Context, sender: str, job: dict) -> None:
    """Place the call, retrying once if nobody picks up, then report back."""
    outcome = await place_call(ctx, job, attempt=1)
    attempts = 1
    if outcome.get("voicemail"):
        await say(ctx, sender, "No answer — it went to voicemail. Trying once more now.")
        outcome = await place_call(ctx, job, attempt=2)
        attempts = 2

    outcome["attempts"] = attempts
    if outcome.get("held"):
        bits = [f"Called {job['to']} and held the room."]
        if outcome.get("door_code"):
            bits.append(f"Door code {outcome['door_code']}.")
        if outcome.get("contact"):
            bits.append(f"Spoke to {outcome['contact']}.")
        if outcome.get("fee_usd"):
            bits.append(f"They charged a ${outcome['fee_usd']:g} late check-in fee.")
        text = " ".join(bits)
    elif outcome.get("voicemail"):
        text = f"Two attempts to {job['to']}, both voicemail. Nothing is held — worth a human call."
    else:
        text = f"The call to {job['to']} did not get the room held. Details: {outcome.get('issues') or 'no outcome reported'}"

    await say(ctx, sender, f"{text}\n\n{json.dumps(outcome)}", end=True)


async def say(ctx: Context, to: str, text: str, end: bool = False) -> None:
    content: list = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    await ctx.send(to, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                   content=content))


# ---------- chat: take the job, then ask to be paid ----------

@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc),
                                               acknowledged_msg_id=msg.msg_id))
    text = "".join(i.text for i in msg.content if isinstance(i, TextContent)).strip()
    if any(isinstance(i, EndSessionContent) for i in msg.content):
        return
    if not text:
        if any(isinstance(i, StartSessionContent) for i in msg.content):
            await say(ctx, sender, "Tell me who to call and what to ask. $1.99 a call.")
        return

    job = parse_job(text)
    reference = f"job-{uuid4().hex[:8]}"
    ctx.storage.set(f"job:{reference}", {"job": job, "buyer": sender})
    ctx.logger.info(f"job {reference} from {sender[:20]}…: {job['purpose']}")

    await say(ctx, sender,
              f"I'll call {job['to']} and {job['purpose']}. I open with: \"{disclosure(job)}\" "
              f"That's ${PRICE_USD} for the call — sending a payment request now.")
    await ctx.send(sender, RequestPayment(
        accepted_funds=[Funds(amount=PRICE_USD, currency=PAYMENT_CURRENCY,
                              payment_method=PAYMENT_METHOD)],
        recipient=str(ctx.agent.address),
        deadline_seconds=PAYMENT_DEADLINE_S,
        reference=reference,
        description=f"One disclosed AI call to {job['to']}: {job['purpose']}",
    ))


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


# ---------- payment: seller side ----------

@pay_proto.on_message(CommitPayment)
async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
    """The buyer committed. Settle (simulated), confirm, then do the work."""
    record = ctx.storage.get(f"job:{msg.reference}") if msg.reference else None
    if not record:
        ctx.logger.warning(f"commit for an unknown job: {msg.reference}")
        return
    if msg.funds.amount != PRICE_USD:
        ctx.logger.warning(f"wrong amount {msg.funds.amount}; expected {PRICE_USD}")
        return

    ctx.logger.info(f"paid {msg.funds.amount} {msg.funds.currency} via "
                    f"{msg.funds.payment_method}, tx {msg.transaction_id}")
    await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))
    ctx.storage.remove(f"job:{msg.reference}")
    await run_job(ctx, sender, record["job"])


@pay_proto.on_message(RejectPayment)
async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
    ctx.logger.info(f"payment declined: {msg.reason}")
    await say(ctx, sender, "No problem — no payment, no call.", end=True)


@agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"Standby Caller ready at {ctx.agent.address}")
    ctx.logger.info(f"${PRICE_USD} per call, settled over {PAYMENT_METHOD} (simulated)")
    ctx.logger.info(f"reachable over the Agentverse mailbox; /submit also listens on "
                    f"port {CALLER_PORT} for senders that take the local shortcut")


agent.include(chat_proto, publish_manifest=True)
agent.include(pay_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
