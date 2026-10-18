"""Standby orchestrator: the ASI:One front door (owner: P2).

Chat Protocol agent that runs the whole disruption flow inside one ASI:One chat:
cancelled -> options -> approve -> book -> call -> result.

Claude phrases the replies and picks the tools; every tool is an HTTP call to the
engine (contract/api.md). The engine owns money: it runs the mandate check, decides
allow/ask/deny and executes the charge. The LLM never decides a spend and never sees
card data.

Run from agents/:  python orchestrator/agent.py
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8000").rstrip("/")
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")  # claude-haiku-4-5 if latency is bad
MAX_TOKENS = 300
MAX_TOOL_HOPS = 6
RESOLVE_TIMEOUT_S = 40  # the mock call takes ~6s; a real ElevenLabs call is slower

# In ASI:One, a message without an @mention goes to the user's own assistant instead of
# here, which silently strands the conversation. Every prompt for a reply names the handle
# so the traveller (and a judge) knows to keep mentioning it. Blank it out for clients
# where mentions are meaningless.
HANDLE = os.getenv("ASI_HANDLE", "@standby").strip()
REPLY_WITH = f'{HANDLE} approve" or "{HANDLE} no' if HANDLE else 'approve" or "no'


# Chat replies are short, so give the whole 300-token budget to the answer rather than
# to thinking. Sonnet 5 reaches for tools less eagerly with thinking off, which is why
# the system prompt spells out when to call each one.
THINKING = {"type": "disabled"}

SYSTEM_PROMPT = """You are Standby, a travel agent for a traveller whose flight was \
just cancelled. You work inside an ASI:One chat.

What you can do: rebook a cancelled flight within the traveller's spending mandate, then \
phone places that have no API (a guesthouse whose front desk closes before they land).

How you work:
- The engine owns every money decision. It runs the mandate check, decides allow / ask / \
deny, and executes the charge. You never decide an amount, never approve a spend on the \
traveller's behalf, and never see or ask for card details.
- You phrase the replies and choose the tools. The facts always come from a tool result, \
never from memory. If you have not called a tool this turn, you do not know the state.

When to call each tool:
- get_booking: the traveller reports a cancellation or asks you to fix their trip. Call it \
first, before anything else. It starts the task and returns the ranked options.
- search_flights: the traveller asks about options, alternatives, or why something was \
ruled out.
- request_approval: you are about to ask the traveller to approve a spend and need the \
exact amount, merchant and remaining budget.
- pay: the traveller has clearly said yes or no to a spend. Pass their answer through; \
the engine decides whether it goes through.
- call_provider: a booking is done and somewhere downstream needs a phone call.
- save_to_vault: a document or transcript should be kept.
- get_status: the traveller asks "status?", "where are we", or anything about progress.
- get_ledger: the traveller asks about money, budget, refunds or what was spent.

How to reply:
- At most 5 short lines. No preamble, no markdown headings, no emoji.
- Lead with what happened. Give the number and the reason, not adjectives.
- When a spend needs the traveller's OK, state the amount, what is left of the budget \
afterwards and the fee allowance, then ask them to reply "REPLY_WITH".
- Always include the handle when you ask them to reply. A reply without it never reaches \
you: the chat sends it to the traveller's own assistant instead.
- Quote money figures exactly as the tool gave them. Never add, subtract or estimate an \
amount yourself.
- Say "book" and "approve", never "pay", "card" or "Visa".

Your reply right after get_booking is the one that matters most. It names the cancelled \
flight, walks through every option the engine ruled out with its reason, then the one it \
picked, then the ask. The blank line after the list matters: the chat renders markdown, \
and without it the recommendation is swallowed into the last bullet. It looks exactly \
like this:

UA183 LAX-SFO is cancelled. Two of the three alternatives are out:

- United UA2104, free, but it lands tomorrow morning and misses SF tonight.
- American AA2401, $319 — over the $300 budget.

That leaves Delta DL1946, 9:15 PM, $215, lands 10:40 tonight. That's $85 of your $300 \
left afterwards, and I'd hold a $50 allowance for fees downstream.

Reply "REPLY_WITH".
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("REPLY_WITH", REPLY_WITH)

TOOLS = [
    {
        "name": "get_booking",
        "description": (
            "Load the traveller's cancelled booking and start a fix task. Returns the "
            "cancelled flight, the ranked alternatives (each with a verdict of pick, ok "
            "or rejected and a one-line reason), and the pending booking approval. Call "
            "this first whenever the traveller reports a cancellation."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_flights",
        "description": (
            "Return the alternative flights ranked by the policy engine, each with its "
            "verdict and the reason it was picked or rejected. Call this when the "
            "traveller asks about options or why one was ruled out."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "request_approval",
        "description": (
            "Return the spend that is waiting on the traveller: amount, merchant, reason, "
            "what is left of the budget and the fee allowance. Call this before asking "
            "them to approve, so the numbers you quote are the engine's."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pay",
        "description": (
            "Record the traveller's answer to the pending spend. The engine runs the "
            "mandate check and executes the charge; you are only passing the answer "
            "through. Only call this once the traveller has clearly said yes or no."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "approved": {
                    "type": "boolean",
                    "description": "True if the traveller approved the spend, false if they declined.",
                },
                "fee_allowance_usd": {
                    "type": "number",
                    "description": (
                        "Extra fees the traveller allows later in the task without being "
                        "asked again, in USD. Use 50 unless they named a different limit."
                    ),
                },
            },
            "required": ["approved"],
        },
    },
    {
        "name": "call_provider",
        "description": (
            "Place a disclosed AI phone call to a business line that has no API, to hold "
            "a room or confirm a booking. Call this once a flight is booked and something "
            "downstream needs a phone call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "purpose": {
                    "type": "string",
                    "description": "What the call should achieve, e.g. hold the room for a late arrival.",
                }
            },
            "required": ["purpose"],
        },
    },
    {
        "name": "save_to_vault",
        "description": "Save a document or call transcript to the traveller's Vault.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["boarding_pass", "call_transcript"],
                    "description": "What kind of record this is.",
                },
                "note": {"type": "string", "description": "One line describing the record."},
            },
            "required": ["type"],
        },
    },
    {
        "name": "get_status",
        "description": (
            "Return the current state of the task: stage, the picked flight, every "
            "approval and its status, and the call outcome. Call this whenever the "
            "traveller asks where things stand."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_ledger",
        "description": (
            "Return the spending mandate and ledger: budget, each spend, refunds, denied "
            "attempts and the remaining budget."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

llm = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from the environment
http = httpx.AsyncClient(base_url=ENGINE_URL, timeout=20.0)

AGENT_SEED = os.getenv("AGENT_SEED")
if not AGENT_SEED:
    raise SystemExit(
        "AGENT_SEED is not set. It decides the agent's address on Agentverse: the "
        "registered Standby agent is agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf. "
        "Put that seed in .env (never in git) before starting the agent."
    )

agent = Agent(
    name="standby",
    seed=AGENT_SEED,
    port=int(os.getenv("ORCHESTRATOR_PORT", "8001")),
    mailbox=True,
    publish_agent_details=True,
    description=(
        "Rebooks cancelled flights within a spending mandate, then phones places with no "
        "API. Handles a cancelled flight end to end: ranks alternatives against the "
        "traveller's budget and deadline, asks once before it spends, books the seat, and "
        "calls the hotel or guesthouse whose front desk closes before you land."
    ),
    readme_path=str(Path(__file__).with_name("README.md")),
)

chat_proto = Protocol(spec=chat_protocol_spec)


# ---------- per-sender state ----------

def load(ctx: Context, sender: str) -> dict:
    return ctx.storage.get(f"chat:{sender}") or {"task_id": None, "approval_id": None, "history": []}


async def ensure_fresh(ctx: Context, state: dict) -> dict:
    """A /demo/reset wipes the engine's task. The chat transcript must not outlive it, or
    the next turn argues about a trip that no longer exists ("already booked", "again")."""
    task_id = state.get("task_id")
    if not task_id:
        return state
    try:
        r = await http.get(f"/tasks/{task_id}")
    except httpx.HTTPError:
        return state  # engine unreachable: keep the context rather than destroying it
    if r.status_code == 404:
        ctx.logger.info("engine task is gone (demo reset) — starting the chat clean")
        return {"task_id": None, "approval_id": None, "history": []}
    return state


def save(ctx: Context, sender: str, state: dict) -> None:
    state["history"] = state["history"][-6:]  # the engine is the source of truth, not the transcript
    ctx.storage.set(f"chat:{sender}", state)


async def say(
    ctx: Context, sender: str, text: str, card: MetadataContent | None = None, end: bool = False
) -> None:
    content: list = [TextContent(type="text", text=text)]
    if card is not None:
        content.append(card)
    if end:
        content.append(EndSessionContent(type="end-session"))
    await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content))


# ---------- ASI:One Interactive Cards ----------
# A card rides along as a MetadataContent block next to the TextContent. If ASI:One can't
# validate it, it silently treats the message as plain text — so the text above every card
# is written to stand on its own, and is what you see in any client without card support.

def card(kind: str, payload: dict, interactive: bool = True, terminal: bool = False) -> MetadataContent:
    meta = {
        "card_protocol_version": "1",
        "requires_card_interaction": "true" if interactive else "false",
        "card_kind": kind,
        "card_payload": json.dumps(payload, separators=(",", ":")),
    }
    if terminal:
        meta["is_terminal"] = "true"
    return MetadataContent(type="metadata", metadata=meta)


def money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) and float(v).is_integer() else f"${v:,.2f}"


def options_carousel(snap: dict) -> MetadataContent | None:
    """The three alternatives. The ones policy ruled out carry the reason and no button,
    which is this surface's version of struck through."""
    options = snap.get("options") or []
    if not options:
        return None
    items = []
    for o in sorted(options, key=lambda x: x.get("verdict") != "pick"):
        rejected = o.get("verdict") == "rejected"
        when = f"{hhmm(o.get('departs'))} {'tomorrow' if o.get('day') != 'today' else 'tonight'}"
        item = {
            "id": o.get("id"),
            "title": f"{o.get('airline')} {o.get('flight')}",
            "subtitle": f"{when} · lands {hhmm(o.get('arrives'))}"
            + (f" · {o['reason']}" if rejected else ""),
            "secondary_text": money(o.get("price_usd")) if o.get("price_usd") else "Free",
        }
        if o.get("verdict") == "pick":
            item["badges"] = [{"label": "Recommended", "variant": "info"}]
            item["primary_cta"] = {
                "label": "Review this",
                "selection": {"action": "review", "option_id": o.get("id")},
            }
        elif not rejected:
            item["primary_cta"] = {
                "label": "Review this",
                "selection": {"action": "review", "option_id": o.get("id")},
            }
        items.append(item)
    booking = snap.get("cancelled") or {}
    return card("carousel", {
        "title": "Rebook UA183",
        "subtitle": booking.get("route") or "LAX → SFO tonight",
        "items": items,
    })


def review_card(snap: dict, approval: dict, fee_allowance: float = 50) -> MetadataContent:
    """The one screen where money is confirmed. Every figure comes from the engine."""
    ledger = snap.get("ledger") or {}
    remaining = ledger.get("remaining_usd")
    amount = approval.get("amount")
    pick = snap.get("pick") or {}
    rows = [{"label": "Flight", "value": f"{pick.get('airline')} {pick.get('flight')}"}] if pick else []
    if pick:
        rows.append({"label": "Departs", "value": f"{hhmm(pick.get('departs'))} tonight"})
        rows.append({"label": "Arrives", "value": hhmm(pick.get("arrives"))})
    rows.append({"label": approval.get("kind", "Spend").title(), "value": money(amount)})
    if remaining is not None and amount is not None:
        rows.append({
            "label": "Budget after this",
            "value": f"{money(remaining - amount)} of {money(ledger.get('budget_usd') or 300)} left",
        })
    rows.append({"label": "Fee allowance", "value": f"up to {money(fee_allowance)} without asking again"})
    return card("review", {
        "title": "Approve this booking",
        "summary_rows": rows,
        "approve_cta": {
            "label": f"Approve {money(amount)}",
            "selection": {"action": "approve", "fee_allowance_usd": fee_allowance},
            "primary": True,
        },
        "reject_cta": {"label": "No, not this one", "selection": {"action": "decline"}},
    })


def result_card(snap: dict) -> MetadataContent:
    outcome = snap.get("outcome") or {}
    ledger = snap.get("ledger") or {}
    pick = snap.get("pick") or {}
    rows = []
    if pick:
        rows.append({"label": "Flight", "value": f"{pick.get('airline')} {pick.get('flight')}, lands {hhmm(pick.get('arrives'))}"})
    rows.append({"label": "Room", "value": "Held" if outcome.get("held") else "Not held"})
    if outcome.get("held") and outcome.get("door_code") and outcome.get("verified"):
        rows.append({"label": "Door code", "value": str(outcome["door_code"])})
    if outcome.get("contact"):
        rows.append({"label": "Spoke to", "value": str(outcome["contact"])})
    if outcome.get("fee_usd"):
        rows.append({"label": "Late check-in fee", "value": money(outcome["fee_usd"])})
    if ledger.get("spent_usd") is not None:
        rows.append({"label": "Spent", "value": f"{money(ledger['spent_usd'])} of {money(ledger.get('budget_usd') or 300)}"})
    if ledger.get("refunds_pending_usd"):
        rows.append({"label": "Refund pending", "value": money(ledger["refunds_pending_usd"])})
    return card("review", {"title": "Sorted for tonight", "summary_rows": rows},
                interactive=False, terminal=True)


def hhmm(t: str | None) -> str:
    if not t or ":" not in str(t):
        return str(t or "")
    h, m = (int(x) for x in str(t).split(":")[:2])
    return f"{h % 12 or 12}:{m:02d} {'PM' if h >= 12 else 'AM'}"


# ---------- engine tools ----------

def brief_options(options: list[dict]) -> list[dict]:
    return [
        {
            "id": o.get("id"),
            "airline": o.get("airline"),
            "flight": o.get("flight"),
            "departs": o.get("departs"),
            "arrives": o.get("arrives"),
            "day": o.get("day"),
            "price_usd": o.get("price_usd"),
            "verdict": o.get("verdict"),
            "reason": o.get("reason"),
        }
        for o in options
    ]


def pending_approval(snapshot: dict) -> dict | None:
    for a in reversed(snapshot.get("approvals") or []):
        if a.get("status") == "pending":
            return a
    return None


async def snapshot(state: dict) -> dict:
    if not state.get("task_id"):
        return {}
    r = await http.get(f"/tasks/{state['task_id']}")
    r.raise_for_status()
    return r.json()


async def run_tool(ctx: Context, state: dict, name: str, args: dict) -> dict:
    """Every tool is an HTTP call to the engine. Returns a dict for the tool_result."""
    if name == "get_booking":
        r = await http.post("/tasks", json={"source": "asi1"})
        r.raise_for_status()
        d = r.json()
        state["task_id"] = d.get("task_id")
        state["approval_id"] = d.get("approval_id")
        state.setdefault("card", "options")
        pick = d.get("pick") or {}
        return {
            "task_id": d.get("task_id"),
            "stage": d.get("stage"),
            "cancelled_flight": "UA183 LAX-SFO",
            "options": brief_options(d.get("options") or []),
            "recommended": pick.get("id"),
            "approval_pending": bool(d.get("approval_id")),
        }

    if name == "search_flights":
        state.setdefault("card", "options")
        if state.get("task_id"):
            snap = await snapshot(state)
            return {"options": brief_options(snap.get("options") or [])}
        r = await http.get("/flights/search")
        r.raise_for_status()
        return {"options": brief_options(r.json().get("options") or [])}

    if name == "request_approval":
        snap = await snapshot(state)
        a = pending_approval(snap)
        if not a:
            return {"pending": False, "note": "nothing is waiting on the traveller right now"}
        state["approval_id"] = a["approval_id"]
        state.setdefault("card", "review")
        ledger = snap.get("ledger") or {}
        remaining = ledger.get("remaining_usd")
        amount = a.get("amount")
        return {
            "pending": True,
            "kind": a.get("kind"),
            "amount_usd": amount,
            "merchant": a.get("merchant"),
            "reason": a.get("reason"),
            "remaining_budget_usd": remaining,
            # Pre-computed so the reply quotes a number instead of doing money arithmetic.
            "remaining_after_this_usd": (
                round(remaining - amount, 2) if remaining is not None and amount is not None else None
            ),
            "suggested_fee_allowance_usd": 50,
        }

    if name == "pay":
        body: dict = {"approved": bool(args.get("approved"))}
        if state.get("approval_id"):
            body["approval_id"] = state["approval_id"]
        elif state.get("task_id"):
            body["task_id"] = state["task_id"]
        if body["approved"]:
            body["fee_allowance_usd"] = float(args.get("fee_allowance_usd") or 50)
            state["fee_allowance"] = body["fee_allowance_usd"]
        state.pop("card", None)  # a decision closes the card it came from
        r = await http.post("/approval", json=body)
        if r.status_code == 404:
            return {"error": "no spend is waiting on the traveller"}
        r.raise_for_status()
        a = r.json()
        state["approval_id"] = None
        state["awaiting_outcome"] = a.get("status") == "approved" and a.get("kind") == "booking"
        return {
            "status": a.get("status"),  # approved, rejected or denied by the mandate
            "kind": a.get("kind"),
            "amount_usd": a.get("amount"),
            "merchant": a.get("merchant"),
        }

    if name == "call_provider":
        # The engine starts the call itself once a booking is paid (contract/api.md has no
        # agent-facing call endpoint yet; see agents/NEEDS.md). Try the endpoint we asked
        # P1 for, and fall back to reporting the call the engine already started.
        try:
            r = await http.post(
                "/call/start",
                json={"task_id": state.get("task_id"), "purpose": args.get("purpose", "hold the room")},
            )
            if r.status_code < 400:
                return r.json()
        except httpx.HTTPError:
            pass
        snap = await snapshot(state)
        return {
            "started_by_engine": snap.get("stage") in ("calling", "fee", "resolved"),
            "stage": snap.get("stage"),
            "outcome": snap.get("outcome"),
        }

    if name == "save_to_vault":
        r = await http.post(
            "/events",
            json={"type": "vault.updated", "data": {"type": args.get("type"), "note": args.get("note")}},
        )
        r.raise_for_status()
        return {"saved": args.get("type")}

    if name == "get_status":
        if not state.get("task_id"):
            return {"stage": "ready", "note": "no task started yet; call get_booking first"}
        snap = await snapshot(state)
        a = pending_approval(snap)
        pick = snap.get("pick") or {}
        stage = snap.get("stage")
        # `pick` is only the engine's recommendation. It becomes a booking when the
        # traveller approves it — reporting it as booked before that would have the agent
        # claim a flight the traveller declined.
        booked = any(a.get("kind") == "booking" and a.get("status") == "approved"
                     for a in (snap.get("approvals") or []))
        flight = f"{pick.get('airline')} {pick.get('flight')}" if pick else None
        return {
            "stage": stage,
            "booked_flight": flight if booked else None,
            "recommended_flight": None if booked else flight,
            "waiting_on_traveller": {"amount_usd": a["amount"], "reason": a["reason"]} if a else None,
            # The engine keeps the last outcome across tasks; only report it once this
            # task has actually resolved, so a stale door code never looks current.
            "call_outcome": snap.get("outcome") if stage == "resolved" else None,
            "remaining_budget_usd": (snap.get("ledger") or {}).get("remaining_usd"),
        }

    if name == "get_ledger":
        r = await http.get("/ledger")
        r.raise_for_status()
        return r.json()

    return {"error": f"unknown tool {name}"}


# ---------- the Claude tool-use loop ----------

async def think(ctx: Context, state: dict, messages: list[dict]) -> str:
    """Run Claude with tools until it stops calling them, returning everything it said.

    Claude often writes the narration in the same response as the tool call it is about
    to make, so text has to be collected from every hop — keeping only the last one
    truncates the reply to its closing sentence."""
    said: list[str] = []
    for _ in range(MAX_TOOL_HOPS):
        response = await llm.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking=THINKING,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason == "refusal":
            return "I can't help with that one. Tell me about the flight and I'll pick it up from there."

        chunk = "".join(b.text for b in response.content if b.type == "text").strip()
        if chunk:
            said.append(chunk)

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            return "\n\n".join(said).strip()

        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
        results = []
        for block in tool_uses:
            try:
                out = await run_tool(ctx, state, block.name, block.input or {})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)})
            except Exception as e:  # keep the chat alive; the engine may be restarting
                ctx.logger.exception(f"tool {block.name} failed")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"tool failed: {e}",
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": results})

    said.append("I'm still working on that. Ask me for the status in a moment.")
    return "\n\n".join(said).strip()


async def wait_for_outcome(ctx: Context, state: dict) -> dict | None:
    """Poll the engine until the booking, the call and the fee have all played out."""
    deadline = asyncio.get_event_loop().time() + RESOLVE_TIMEOUT_S
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(1.5)
        try:
            snap = await snapshot(state)
        except httpx.HTTPError:
            continue
        if snap.get("stage") == "resolved":
            return snap
        a = pending_approval(snap)
        if a:  # the engine is asking the traveller again (a fee above the allowance)
            state["approval_id"] = a["approval_id"]
            return snap
    return None


def as_instruction(text: str, state: dict) -> str:
    """A card CTA arrives as a JSON selection string (or, through the planner, as prose).
    Turn JSON into the sentence the traveller would have typed, so one path handles both
    and the text flow stays the fallback."""
    try:
        sel = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(sel, dict):
        return text
    action = sel.get("action")
    if action == "review":
        return "Show me the details for that option before I decide."
    if action == "approve":
        allowance = sel.get("fee_allowance_usd")
        state["fee_allowance"] = float(allowance) if allowance is not None else 50.0
        return f"Approve it, and allow up to ${state['fee_allowance']:g} in fees downstream."
    if action == "decline":
        return "No, don't book that one."
    return text


async def build_card(ctx: Context, state: dict) -> MetadataContent | None:
    """Attach whichever card the tools Claude just called implies. Any failure here is
    non-fatal: the reply still goes out as text."""
    kind = state.pop("card", None)
    if not kind or not state.get("task_id"):
        return None
    try:
        snap = await snapshot(state)
        if kind == "options":
            return options_carousel(snap)
        if kind == "review":
            a = pending_approval(snap)
            if a:
                return review_card(snap, a, state.get("fee_allowance", 50))
    except Exception:
        ctx.logger.exception("card build failed; sending text only")
    return None


# ---------- chat protocol ----------

@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )

    text = "".join(item.text for item in msg.content if isinstance(item, TextContent)).strip()
    starting = any(isinstance(item, StartSessionContent) for item in msg.content)
    ending = any(isinstance(item, EndSessionContent) for item in msg.content)

    if ending:
        ctx.storage.remove(f"chat:{sender}")
        return
    if not text:
        if starting:
            await say(ctx, sender, "Tell me what went wrong with your trip and I'll handle it.")
        return

    state = await ensure_fresh(ctx, load(ctx, sender))
    text = as_instruction(text, state)  # a card tap arrives as JSON; treat it as if typed
    state["history"].append({"role": "user", "content": text})
    messages = list(state["history"])

    try:
        reply = await think(ctx, state, messages)
    except Exception:
        ctx.logger.exception("turn failed")
        save(ctx, sender, state)
        await say(ctx, sender, "Something broke on my side. Say 'status?' and I'll pick up where we left off.")
        return

    state["history"].append({"role": "assistant", "content": reply})

    # A booking was just approved: the engine now books, declines the airline's offer and
    # phones the guesthouse. Report that, then report the outcome when it lands.
    if state.pop("awaiting_outcome", False):
        save(ctx, sender, state)
        await say(ctx, sender, reply)
        snap = await wait_for_outcome(ctx, state)
        if snap is None:
            await say(ctx, sender, "The call is still running. Say 'status?' in a moment.")
            return
        follow = list(state["history"]) + [
            {
                "role": "user",
                "content": (
                    "The task finished while you waited. Report the outcome to the traveller in at "
                    f"most 4 short lines, using only these facts: {json.dumps({'stage': snap.get('stage'), 'outcome': snap.get('outcome'), 'ledger': snap.get('ledger')})}"
                ),
            }
        ]
        try:
            final = await think(ctx, state, follow)
        except Exception:
            ctx.logger.exception("outcome turn failed")
            final = "The room is held. Say 'status?' for the details."
        state["history"].append({"role": "assistant", "content": final})
        state.pop("card", None)
        save(ctx, sender, state)
        resolved = snap.get("stage") == "resolved"
        await say(ctx, sender, final, card=result_card(snap) if resolved else None, end=resolved)
        return

    save(ctx, sender, state)
    await say(ctx, sender, reply, card=await build_card(ctx, state))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"Standby orchestrator ready at {ctx.agent.address}")
    ctx.logger.info(f"engine: {ENGINE_URL}  model: {MODEL}")


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
