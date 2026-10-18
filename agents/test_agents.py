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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "orchestrator"))

logging.getLogger("asyncio").setLevel(logging.CRITICAL)  # the Agent object we import is never run
warnings.filterwarnings("ignore", message="coroutine 'Agent.publish_manifest'")
logging.basicConfig(level=logging.CRITICAL)

import agent as orch  # noqa: E402

GREEN, RED, DIM, CYAN, RESET = "\033[32m", "\033[31m", "\033[90m", "\033[36m", "\033[0m"
checks = 0


class Ctx:
    """Stands in for a uAgents Context. `sent` records outbound messages so tests can
    assert on them without a running agent."""
    logger = logging.getLogger("test")

    def __init__(self):
        self.sent: list = []

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
    assert "$50" in rows["Fee allowance"], rows
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

    msg = orch.as_instruction('{"action":"approve","fee_allowance_usd":50}', s)
    assert "approve" in msg.lower() and s["fee_allowance"] == 50, (msg, s)
    ok("an Approve tap carries the fee allowance through")

    assert "don't book" in orch.as_instruction('{"action":"decline"}', s).lower()
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
