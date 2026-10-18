"""Tests for the Standby agents (owner: P2).

    cd agents && python test_agents.py          # tool layer + cards, no LLM calls
    cd agents && python test_agents.py --live   # also drives Claude end to end

Needs the engine running on ENGINE_URL (default http://localhost:8000).
Run this before opening a PR, the same way engine/test_engine.py is run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import warnings
from datetime import timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent / "orchestrator"))

logging.getLogger("asyncio").setLevel(logging.CRITICAL)  # the Agent object we import is never run
warnings.filterwarnings("ignore", message="coroutine 'Agent.publish_manifest'")
logging.basicConfig(level=logging.CRITICAL)

import agent as orch  # noqa: E402

GREEN, RED, DIM, CYAN, RESET = "\033[32m", "\033[31m", "\033[90m", "\033[36m", "\033[0m"
checks = 0


class Store:
    """ctx.storage, in memory."""

    def __init__(self):
        self.d: dict = {}

    def get(self, key):
        return self.d.get(key)

    def set(self, key, value):
        self.d[key] = value

    def remove(self, key):
        self.d.pop(key, None)


class Ctx:
    """Stands in for a uAgents Context. `sent` records outbound messages so tests can
    assert on them without a running agent."""
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent: list = []
        self.storage = Store()

    async def send(self, to, message):
        self.sent.append((to, message))


def ok(label: str) -> None:
    global checks
    checks += 1
    print(f"  {GREEN}✓{RESET} {label}")


def section(name: str) -> None:
    print(f"\n{CYAN}{name}{RESET}")


async def reset() -> None:
    await orch.http.post("/demo/reset")


# ---------- the engine tools ----------

async def test_ask_live(live: bool) -> None:
    """ask_live relays a free question to the engine's POST /ask. It never touches the glasses
    (show: false) and never starts a task; without Claude on the engine it says so instead of raising."""
    section("ask_live")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}
    assert "ask_live" in {t["name"] for t in orch.TOOLS}
    assert (await orch.run_tool(Ctx(), s, "ask_live", {"question": "  "}))["error"] == "no question"
    before = (await orch.http.get("/state")).json()
    d = await orch.run_tool(Ctx(), s, "ask_live", {"question": "Is UA1 on time? Which gate?"})
    after = (await orch.http.get("/state")).json()
    assert ("answer" in d) or d["error"].startswith("live answers unavailable"), d
    assert after["screen"] == before["screen"] and after["stage"] == "ready" and after["task_id"] is None
    ok("ask_live answers (or says it can't), leaves the glasses alone and starts no task")
    if live:
        assert d.get("answer") and d.get("live"), f"needs ANTHROPIC_API_KEY and AEROAPI_KEY on the engine: {d}"
        print(f"{DIM}{d['answer']}{RESET}")
        ok("ask_live: a real flight answered live from FlightAware")


async def test_tools() -> dict:
    section("engine tools")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}

    d = await orch.run_tool(Ctx(), s, "get_booking", {})
    assert d["task_id"] and d["approval_pending"], d
    assert len(d["options"]) == 3, d["options"]
    assert d["recommended"] == "opt-delta", d["recommended"]
    verdicts = {o["id"]: o["verdict"] for o in d["options"]}
    assert verdicts == {"opt-united": "rejected", "opt-american": "rejected", "opt-delta": "pick"}, verdicts
    ok("get_booking starts a task and the policy rules out 2 of 3 options")

    a = await orch.run_tool(Ctx(), s, "request_approval", {})
    assert a["pending"] and a["amount_usd"] == 215, a
    assert a["remaining_budget_usd"] == 300 and a["remaining_after_this_usd"] == 85, a
    ok("request_approval returns the spend, the budget and the budget after it")

    p = await orch.run_tool(Ctx(), s, "pay", {"approved": True, "fee_allowance_usd": 50})
    assert p["status"] == "approved" and p["amount_usd"] == 215, p
    assert s.get("awaiting_outcome"), "approving a booking must start the wait for the outcome"
    ok("pay passes the answer to the engine, which approves and charges it")

    snap = await orch.wait_for_outcome(Ctx(), s)
    assert snap and snap["stage"] == "resolved", snap and snap.get("stage")
    # a subset, not equality: the engine may add fields (it added `summary`), and the
    # contract allows that. Assert only what the agent actually reads.
    expected = {"held": True, "fee_usd": 40, "door_code": "4417",
                "contact": "Maria", "verified": True}
    assert expected.items() <= snap["outcome"].items(), snap["outcome"]
    ok("the call runs and the task resolves: room held, door code verified")

    st = await orch.run_tool(Ctx(), s, "get_status", {})
    assert st["stage"] == "resolved" and st["remaining_budget_usd"] == 45, st
    led = await orch.run_tool(Ctx(), s, "get_ledger", {})
    assert led["spent_usd"] == 255 and led["refunds_pending_usd"] == 189 and led["net_cost_usd"] == 66, led
    ok("the ledger adds up: $255 spent, $189 refund pending, $66 net")

    assert (await orch.run_tool(Ctx(), s, "save_to_vault", {"type": "call_transcript"}))["saved"]
    ok("save_to_vault records to the Vault")
    return snap


async def test_guardrails() -> None:
    section("guardrails")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}

    # a status question before anything has started must not invent a trip
    assert (await orch.run_tool(Ctx(), {"task_id": None}, "get_status", {}))["stage"] == "ready"
    ok("get_status with no task says ready instead of inventing one")

    await orch.run_tool(Ctx(), s, "get_booking", {})
    d = await orch.run_tool(Ctx(), s, "pay", {"approved": False})
    assert d["status"] == "rejected", d
    assert not s.get("awaiting_outcome"), "a decline must not wait for a call that never happens"
    st = await orch.run_tool(Ctx(), s, "get_status", {})
    assert st["booked_flight"] is None and st["call_outcome"] is None, st
    ok("declining books nothing, and no stale outcome leaks from an earlier task")

    # ASI:One relays one conversation from several sender addresses: the options go to
    # one, "approve" arrives at another. A chat with no task must pick up the live one.
    await reset()
    first = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), first, "get_booking", {})
    other_relay = await orch.ensure_fresh(Ctx(), {"task_id": None, "approval_id": None, "history": []})
    assert other_relay["task_id"] == first["task_id"], (other_relay, first["task_id"])
    assert other_relay["approval_id"], "the pending approval must come across too"
    paid = await orch.run_tool(Ctx(), other_relay, "pay", {"approved": True})
    assert paid["status"] == "approved", paid
    ok("a turn arriving from a different relay address adopts the task and can approve it")

    # paying twice for one call would be a real loss, so it is blocked in code
    await reset()
    s2 = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), s2, "get_booking", {})
    await orch.run_tool(Ctx(), s2, "pay", {"approved": True, "fee_allowance_usd": 50})
    saved_addr = orch.CALLER_ADDRESS
    orch.CALLER_ADDRESS = "agent1qtest"
    try:
        ctx = Ctx()
        res = await orch.run_tool(ctx, s2, "hire_caller", {"purpose": "hold the room"})
        assert "not_hired" in res, res
        assert not ctx.sent, "nothing should have been sent to the Caller"
    finally:
        orch.CALLER_ADDRESS = saved_addr
    ok("the Caller is not hired, or paid, while the engine already has a call in flight")

    # right after the booking the engine is about to place its own call (stage "booked"):
    # hiring the Caller then ran a simulated call that beat the real one (seen live)
    real_snapshot = orch.snapshot

    async def booked(_state):
        return {"stage": "booked"}
    orch.snapshot = booked
    try:
        ctx = Ctx()
        res = await orch.run_tool(ctx, {"task_id": "task-x", "approval_id": None, "history": []},
                                  "hire_caller", {"purpose": "hold the room"})
    finally:
        orch.snapshot = real_snapshot
    assert res.get("not_hired") and ctx.sent == [], res
    ok("the Caller is not hired between the booking and the engine's own call")
    # The booking turn must not let the model tell the traveller it hired the Caller:
    # the engine places that call itself, and nothing was paid to anyone.
    await reset()
    s5 = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), s5, "get_booking", {})
    paid = await orch.run_tool(Ctx(), s5, "pay", {"approved": True, "fee_allowance_usd": 50})
    assert "Standby is placing" in paid.get("doing_now", ""), paid
    assert "no Caller agent was hired" in paid.get("doing_now", ""), paid
    assert "1.99" not in json.dumps(paid), paid
    ok("the booking turn says the engine is calling, not that a Caller was hired")

    # An unreachable engine must not be a licence to spend. Fail closed mid-task.
    s6 = {"task_id": "task-live", "approval_id": None, "history": []}
    saved_addr, saved_snapshot = orch.CALLER_ADDRESS, orch.snapshot
    orch.CALLER_ADDRESS = "agent1qtest"

    async def unreachable(_state):
        raise httpx.ConnectError("engine down")

    orch.snapshot = unreachable
    try:
        ctx = Ctx()
        res = await orch.run_tool(ctx, s6, "hire_caller", {"purpose": "hold the room"})
        assert "not_hired" in res, res
        assert not ctx.sent, "an unreachable engine must not trigger a paid call"
    finally:
        orch.CALLER_ADDRESS, orch.snapshot = saved_addr, saved_snapshot
    ok("an unreachable engine mid-task refuses the hire instead of spending anyway")

    # "hired" only means a job went out. If the Caller never charged — it timed out, or
    # never asked — the reply must not say a fee was covered on the traveller's behalf.
    await reset()
    s7 = {"task_id": None, "approval_id": None, "history": []}
    saved_addr, saved_timeout = orch.CALLER_ADDRESS, orch.CALL_RESULT_TIMEOUT_S
    orch.CALLER_ADDRESS, orch.CALL_RESULT_TIMEOUT_S = "agent1qtest", 0.2
    try:
        res = await orch.run_tool(Ctx(), s7, "hire_caller", {"purpose": "hold the room"})
        assert "fee_paid" not in res, res
        assert "no_fee_was_paid" in res and "say_nothing_about_money" in res, res
        assert "Payment Protocol" not in json.dumps({k: v for k, v in res.items()
                                                     if k != "say_nothing_about_money"}), res
    finally:
        orch.CALLER_ADDRESS, orch.CALL_RESULT_TIMEOUT_S = saved_addr, saved_timeout
    ok("a hire the Caller never charged for reports no fee instead of inventing one")

    # running the demo twice without a manual reset must still work
    s4 = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), s4, "get_booking", {})
    await orch.run_tool(Ctx(), s4, "pay", {"approved": True, "fee_allowance_usd": 50})
    assert (await orch.wait_for_outcome(Ctx(), s4))["stage"] == "resolved"
    again = await orch.run_tool(Ctx(), {"task_id": None, "approval_id": None, "history": []},
                                "get_booking", {})
    picked = [o for o in again["options"] if o["verdict"] == "pick"]
    assert picked and picked[0]["id"] == "opt-delta", (
        f"a second run must start on a full budget, got {[(o['id'], o['verdict']) for o in again['options']]}")
    ok("a second run back-to-back starts on a full budget instead of a spent one")

    # a reset while a turn is in flight must not throw
    s3 = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), s3, "get_booking", {})
    await reset()
    st = await orch.run_tool(Ctx(), s3, "get_status", {})
    assert st["stage"] == "ready", st
    ok("a reset mid-turn degrades to live engine state instead of raising")

    # the engine, not the model, is the source of truth after a reset
    await reset()
    fresh = await orch.ensure_fresh(Ctx(), {"task_id": s["task_id"], "approval_id": None,
                                            "history": [{"role": "user", "content": "old"}]})
    assert fresh["history"] == [] and fresh["task_id"] is None, fresh
    ok("a /demo/reset clears the chat transcript instead of arguing about a dead trip")

    # a relay that remembers an OLD task sends "approve" while a NEW task waits on a spend
    # (seen live in ASI:One: "There's nothing pending for you to approve right now")
    old = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), old, "get_booking", {})
    await reset()
    new = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), new, "get_booking", {})
    adopted = await orch.ensure_fresh(Ctx(), {**old, "history": [{"role": "user", "content": "old"}]})
    assert adopted["task_id"] == new["task_id"] and adopted["approval_id"], adopted
    a = await orch.run_tool(Ctx(), adopted, "request_approval", {})
    assert a["pending"] and a["amount_usd"] == 215, a
    ok("a relay with a stale task adopts the one in flight, so its approve reaches the pending spend")

    # ASI:One keys every chat with the same relay address, so a new chat opened the next
    # morning used to arrive holding last night's transcript — and the agent answered a
    # fresh "UA183 is cancelled" with "already handled", never calling get_booking.
    ctx, who = Ctx(), "agent1relay"
    orch.save(ctx, who, {"task_id": "task-old", "approval_id": None,
                         "history": [{"role": "user", "content": "UA183 is cancelled"},
                                     {"role": "assistant", "content": "Booked DL1402, room held."}]})
    assert orch.load(ctx, who)["history"], "a turn moments later is still the same chat"
    stale = ctx.storage.get(f"chat:{who}")
    stale["last_turn"] = (orch.datetime.now(orch.timezone.utc)
                          - timedelta(seconds=orch.CHAT_TTL_S + 60)).isoformat()
    ctx.storage.set(f"chat:{who}", stale)
    assert orch.load(ctx, who) == {"task_id": None, "approval_id": None, "history": []}
    ctx.storage.set(f"chat:{who}", {"task_id": "task-old", "approval_id": None, "history": [1]})
    assert orch.load(ctx, who)["task_id"] is None, "state saved before last_turn existed is stale too"
    ok("a chat opened long after the last turn starts clean instead of 'already handled'")

    # the explicit signal, when ASI:One sends one: a new session drops the old transcript
    ctx, who = Ctx(), "agent1relay2"
    orch.save(ctx, who, {"task_id": "task-old", "approval_id": None,
                         "history": [{"role": "user", "content": "old"}]})
    await orch.handle_message(ctx, who, orch.ChatMessage(
        timestamp=orch.datetime.now(orch.timezone.utc), msg_id=orch.uuid4(),
        content=[orch.StartSessionContent(type="start-session")]))
    assert ctx.storage.get(f"chat:{who}") is None, ctx.storage.d
    ok("a start-session clears the previous conversation held under the same relay address")


# ---------- the Payment Protocol handshake, narrated ----------

async def test_handshake_narration() -> None:
    """A hire's protocol steps reach the traveller's chat as they happen, written by code,
    and Claude is told they were shown. Drives the buyer-side handlers directly."""
    from uagents_core.contrib.protocols.payment import (CompletePayment, Funds, RejectPayment,
                                                        RequestPayment)
    section("Payment Protocol handshake, narrated in the chat")
    saved = orch.CALLER_ADDRESS
    orch.CALLER_ADDRESS = caller = "agent1qcaller"
    ask = lambda amount: RequestPayment(  # noqa: E731
        accepted_funds=[Funds(amount=amount, currency="USD", payment_method="fet_direct")],
        recipient=caller, deadline_seconds=120, reference="job-1", description="one call")

    def chat(ctx: Ctx) -> list[str]:
        return ["".join(c.text for c in m.content if hasattr(c, "text")).strip("`")
                for to, m in ctx.sent if to == "traveller"]

    async def until(cond):
        for _ in range(100):
            if cond():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("handler never ran")

    try:
        ctx = Ctx()
        s = {"task_id": None, "approval_id": None, "history": [], "reply_to": "traveller"}
        hire = asyncio.create_task(orch.run_tool(ctx, s, "hire_caller", {"purpose": "hold the room"}))
        await until(lambda: orch.open_job())
        await orch.on_payment_request(ctx, caller, ask("1.99"))
        tx = next(m.transaction_id for to, m in ctx.sent if type(m).__name__ == "CommitPayment")
        await orch.on_payment_complete(ctx, caller, CompletePayment(transaction_id=tx))
        await orch.handle_message(ctx, caller, orch.ChatMessage(
            timestamp=orch.datetime.now(orch.timezone.utc), msg_id=orch.uuid4(),
            content=[orch.TextContent(type="text", text="Held.\n" + json.dumps(
                {"held": True, "door_code": "4417", "verified": True, "fee_usd": 40,
                 "attempts": 1, "mode": "mock"}))]))
        res = await hire
        lines = chat(ctx)
        assert [l.split(" · ")[0] for l in lines] == [
            "→ @standby-caller", "← RequestPayment", "→ CommitPayment",
            "← CompletePayment", "← outcome"], lines
        assert f"tx {tx}" in lines[2] and "$2.00/call cap" in lines[2], lines[2]
        assert "door code 4417" in lines[4] and "simulated call" in lines[4], lines[4]
        assert res["traveller_already_saw"] == lines and res["fee_paid"].startswith("1.99 USD"), res
        ok("job → RequestPayment → CommitPayment → CompletePayment → outcome, one line each, in order")

        ctx = Ctx()
        hire = asyncio.create_task(orch.run_tool(ctx, s, "hire_caller", {"purpose": "hold the room"}))
        await until(lambda: orch.open_job())
        await orch.on_payment_request(ctx, caller, ask("9.99"))
        res = await asyncio.wait_for(hire, 1)  # not the 45s timeout
        assert any(isinstance(m, RejectPayment) for _, m in ctx.sent)
        assert chat(ctx)[-1].startswith("→ RejectPayment") and "not hired" in res["outcome"]["error"], res
        ok("a price over the cap is rejected, shown, and ends the hire at once")
    finally:
        orch.CALLER_ADDRESS = saved


# ---------- a fee mid-call needs the traveller's yes ----------

async def test_fee_consent() -> None:
    """ASI:One used to send a $50 fee allowance with every approve, so the guesthouse's
    $40 was charged without asking. Now, as on the glasses, the fee comes back to the
    traveller, and only their own yes approves it."""
    section("a fee during the call is asked for, never assumed")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(Ctx(), s, "get_booking", {})
    s["said_yes"] = True
    p = await orch.run_tool(Ctx(), s, "pay", {"approved": True})
    assert p["status"] == "approved", p
    snap = await orch.wait_for_outcome(Ctx(), s)
    a = orch.pending_approval(snap)
    assert snap["stage"] == "fee" and a and a["kind"] == "fee" and a["amount"] == 40, snap.get("stage")
    assert snap["ledger"]["spent_usd"] == 215, "the fee must not be charged before the traveller answers"
    ok("approving the booking does not pre-approve the $40 fee: the call stops and asks")

    ask = orch.fee_ask(snap, a)
    assert "$40" in ask and "$45 of your $300" in ask and "approve" in ask, ask
    rows = {r["label"]: r["value"] for r in json.loads(orch.review_card(snap, a).metadata["card_payload"])["summary_rows"]}
    assert rows["Fee"] == "$40" and rows["Budget after this"] == "$45 of $300 left", rows
    ok("the ask quotes the engine's figures, with a review card for the fee")

    s["said_yes"] = orch.explicit_yes("what's happening with the call?")
    no = await orch.run_tool(Ctx(), s, "pay", {"approved": True})
    assert "not_done" in no, no
    assert (await orch.http.get("/state")).json()["stage"] == "fee", "a question must not approve the fee"
    ok("a question mid-call cannot approve the fee, whatever the model calls")

    for typed, yes in (("approve", True), ("@standby approve", True), ("yes", True), ("ok do it", True),
                       ("no", False), ("don't approve", False), ("why not the American one?", False),
                       ("thanks", False), ("is it done?", False)):
        assert orch.explicit_yes(typed) is yes, typed
    ok("only a plain yes counts as consent")

    s["said_yes"] = orch.explicit_yes("@standby approve")
    p = await orch.run_tool(Ctx(), s, "pay", {"approved": True})
    assert p["status"] == "approved" and p["kind"] == "fee" and s.get("awaiting_outcome"), p
    snap = await orch.wait_for_outcome(Ctx(), s)
    assert snap["stage"] == "resolved" and snap["ledger"]["spent_usd"] == 255, snap.get("stage")
    ok("the traveller's yes approves the fee and the call finishes")

    # The chat used to watch the call only inside the approve turn, for a fixed window. A
    # real call reaches the fee later than that, so the fee was never asked for and the
    # result never arrived until the traveller said "status?". The watcher runs past the
    # turn: it asks for the fee when it comes up and posts the result when the call ends.
    await reset()
    ctx, who = Ctx(), "traveller"
    s = {"task_id": None, "approval_id": None, "history": []}
    await orch.run_tool(ctx, s, "get_booking", {})
    s["said_yes"] = True
    await orch.run_tool(ctx, s, "pay", {"approved": True})
    orch.save(ctx, who, s)
    saved_think = orch.think
    orch.think = lambda *a, **k: asyncio.sleep(0, "Room held, door code 4417.")
    try:
        orch.watch_call(ctx, who, s["task_id"])
        orch.watch_call(ctx, who, s["task_id"])  # a second turn must not start a second watcher
        texts = lambda: ["".join(c.text for c in m.content if hasattr(c, "text")) for _, m in ctx.sent]  # noqa: E731
        for _ in range(300):
            if any("$40" in t for t in texts()):
                break
            await asyncio.sleep(0.1)
        assert [t for t in texts() if "$40" in t] and len(texts()) == 1, texts()
        assert orch.load(ctx, who)["approval_id"], "the chat must hold the fee so 'approve' answers it"
        ok("the watcher asks for the fee in the chat as soon as the call reaches it")

        s = orch.load(ctx, who)
        s["said_yes"] = True
        await orch.run_tool(ctx, s, "pay", {"approved": True})
        await asyncio.wait_for(orch.watching[s["task_id"]], 30)
        last = ctx.sent[-1][1]
        assert "door code 4417" in texts()[-1] and any(type(c).__name__ == "EndSessionContent" for c in last.content)
        assert not orch.watching, orch.watching
        ok("after the fee is answered, the same watcher posts the result when the call ends")
    finally:
        orch.think = saved_think


# ---------- interactive cards ----------

REQUIRED = {"card_protocol_version", "requires_card_interaction", "card_kind", "card_payload"}
KINDS = {"carousel", "detail", "form", "review", "custom"}


def valid(mc, label: str) -> dict:
    assert mc is not None, f"{label}: no card produced"
    m = mc.metadata
    assert mc.type == "metadata", label
    assert REQUIRED <= set(m), f"{label}: missing {REQUIRED - set(m)}"
    assert m["card_kind"] in KINDS, f"{label}: bad kind {m['card_kind']}"
    assert all(isinstance(v, str) for v in m.values()), f"{label}: metadata must be all strings"
    size = len(m["card_payload"].encode())
    assert size <= 64 * 1024, f"{label}: payload {size}B over the 64KB limit"
    return json.loads(m["card_payload"])


async def test_cards(resolved: dict) -> None:
    section("interactive cards")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}

    await orch.run_tool(Ctx(), s, "get_booking", {})
    car = valid(await orch.build_card(Ctx(), s), "carousel")
    assert car["items"][0]["badges"][0]["label"] == "Recommended", "the pick must sort first"
    sel = [i for i in car["items"] if "primary_cta" in i]
    out = [i for i in car["items"] if "primary_cta" not in i]
    assert len(sel) == 1 and len(out) == 2, f"{len(sel)} selectable, {len(out)} ruled out"
    for i in out:
        assert any(w in i["subtitle"] for w in ("misses", "over the")), f"no reason on {i['id']}"
    ok("options carousel: pick is badged and selectable, the other 2 carry their reason, no button")

    await orch.run_tool(Ctx(), s, "request_approval", {})
    rev = valid(await orch.build_card(Ctx(), s), "review")
    rows = {r["label"]: r["value"] for r in rev["summary_rows"]}
    assert rows["Booking"] == "$215", rows
    assert rows["Budget after this"] == "$85 of $300 left", rows
    assert "ask you" in rows["Fees later"], rows
    assert rev["approve_cta"]["selection"]["action"] == "approve"
    assert rev["reject_cta"]["selection"]["action"] == "decline"
    ok("review card: the engine's figures, Approve and decline")

    res = valid(orch.result_card(resolved), "result")
    rows = {r["label"]: r["value"] for r in res["summary_rows"]}
    assert rows["Door code"] == "4417" and rows["Room"] == "Held", rows
    assert rows["Spent"] == "$255 of $300", rows
    ok("result card: outcome and ledger, terminal and not interactive")


def test_selection_parsing() -> None:
    section("card taps and typed replies take the same path")
    s: dict = {}
    assert "details" in orch.as_instruction('{"action":"review","option_id":"opt-delta"}', s).lower()
    ok("a Review tap becomes a request to see the details")

    assert orch.as_instruction('{"action":"approve"}', s) == "Approve it."
    assert "$50" in orch.as_instruction('{"action":"approve","fee_allowance_usd":50}', s)
    ok("an Approve tap approves, with no fee allowance unless the card carried one")

    assert "don't approve" in orch.as_instruction('{"action":"decline"}', s).lower()
    ok("a decline tap reads as a decline")

    for typed in ("approve", "why not the American one?", "status?", "{not json"):
        assert orch.as_instruction(typed, s) == typed, typed
    ok("typed text passes through untouched, so the text flow stays the fallback")


# ---------- the live Claude loop ----------

async def test_live() -> None:
    section("live Claude loop (--live)")
    await reset()
    s = {"task_id": None, "approval_id": None, "history": []}

    reply = await orch.think(Ctx(), s, [{"role": "user", "content": "My UA183 got cancelled, handle it"}])
    print(f"{DIM}{reply}{RESET}")
    low = reply.lower()
    assert "ua183" in low and "dl1946" in low, "the reply must name the cancelled flight and the pick"
    assert "ua2104" in low and "aa2401" in low, "both ruled-out options must be mentioned"
    assert "215" in reply, "the price must come from the engine"
    assert s.get("card") == "options", "the carousel should be queued"
    ok("one turn: calls the engine, names the cancelled flight and both rejected options")

    s["history"] = [{"role": "user", "content": "My UA183 got cancelled, handle it"},
                    {"role": "assistant", "content": reply}]
    reply2 = await orch.think(Ctx(), s, s["history"] + [{"role": "user", "content": "approve"}])
    print(f"{DIM}{reply2}{RESET}")
    assert s.get("awaiting_outcome"), "approving must book and start the wait"
    ok("approving books the flight through the engine")

    snap = await orch.wait_for_outcome(Ctx(), s)
    assert snap and snap["stage"] == "resolved"
    ok("the call completes and the task resolves")

    # The reported bug, from the model's side: with a finished trip in the transcript, a
    # fresh cancellation was answered "already handled" out of memory, and get_booking —
    # the only thing that resets the engine — was never called. load() now drops a stale
    # transcript, but the prompt has to hold even when the history legitimately survives.
    done_task = s["task_id"]
    s["history"] = [{"role": "user", "content": "approve"},
                    {"role": "assistant", "content": "Booked DL1946. Room held, door code 4417."}]
    reply3 = await orch.think(Ctx(), s, s["history"]
                              + [{"role": "user", "content": "My UA183 got cancelled, handle it"}])
    print(f"{DIM}{reply3}{RESET}")
    assert s["task_id"] and s["task_id"] != done_task, (
        f"a fresh cancellation must start a new task, not answer from the last one: {reply3}")
    assert "215" in reply3, f"the new task's figures must come from the engine: {reply3}"
    ok("a cancellation after a finished trip starts a new task instead of 'already handled'")


async def main() -> None:
    live = "--live" in sys.argv
    try:
        await orch.http.get("/state")
    except Exception:
        print(f"{RED}engine not reachable at {orch.ENGINE_URL} — start it first:{RESET}\n"
              f"  cd engine && uvicorn app.main:app --port 8000")
        sys.exit(1)

    await test_ask_live(live)
    resolved = await test_tools()
    await test_guardrails()
    await test_handshake_narration()
    await test_fee_consent()
    await test_cards(resolved)
    test_selection_parsing()
    if live:
        await test_live()
    else:
        print(f"\n{DIM}skipping the live Claude loop; re-run with --live to include it{RESET}")

    await reset()
    await orch.http.aclose()
    print(f"\n{GREEN}agents ok — {checks} checks passed{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
