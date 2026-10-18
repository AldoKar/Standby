"""Handle It orchestrator: the ASI:One front door (owner: P2).

A Chat Protocol agent that runs the whole flow inside an ASI:One chat by calling
the same engine the glasses use. Fetch requires the complete primary workflow
to run in ASI:One with no custom frontend.

Run:  BACKEND_URL=https://<engine> python orchestrator/agent.py
Then open the inspector link it prints and connect the mailbox to Agentverse.
"""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
FEE_ALLOWANCE_USD = 50  # set on the review card; covers mid-call fees in chat

agent = Agent(
    name="handle-it",
    seed=os.getenv("ORCHESTRATOR_SEED", "handle-it orchestrator dev seed, change me"),
    port=int(os.getenv("ORCHESTRATOR_PORT", "8001")),
    mailbox=True,
)
chat_proto = Protocol(spec=chat_protocol_spec)


def text(msg: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=msg)])


def clock(t: str) -> str:
    h, m = (int(x) for x in t.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'PM' if h >= 12 else 'AM'}"


def options_message(task: dict) -> str:
    # TODO(P2): send this as an Interactive Card (carousel + review card) once the format is confirmed.
    lines = ["I checked the flights that still get you to SF tonight:"]
    for o in task["options"]:
        mark = "✓" if o["verdict"] == "pick" else "✗"
        lines.append(f"{mark} {o['airline']} {o['flight']}, {clock(o['departs'])}, ${o['price_usd']}: {o['reason']}")
    p = task["pick"]
    lines.append(f"\nReply \"book\" to book {p['airline']} {clock(p['departs'])} for ${p['price_usd']} "
                 f"(extra fees OK up to ${FEE_ALLOWANCE_USD}).")
    return "\n".join(lines)


def outcome_message(state: dict) -> str:
    o, ledger = state.get("outcome") or {}, state["ledger"]
    if o.get("held"):
        head = f"Done. Room held at the guesthouse, door code {o['door_code']}, ask for {o.get('contact')}."
    else:
        head = "The flight is booked, but the guesthouse couldn't hold the room."
    return (f"{head}\nSpent ${ledger['spent_usd']:g} of ${ledger['mandate']['budget_usd']:g}; "
            f"United refund ${ledger['refunds_pending_usd']:g} pending; net ${ledger['net_cost_usd']:g}.")


async def wait_for_outcome(api: httpx.AsyncClient, task_id: str, timeout_s: int = 150) -> dict:
    for _ in range(timeout_s // 2):
        state = (await api.get(f"/tasks/{task_id}")).json()
        if state["stage"] == "resolved":
            return state
        await asyncio.sleep(2)
    raise TimeoutError("call is taking too long")


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    for item in msg.content:
        if isinstance(item, StartSessionContent):
            ctx.logger.info(f"Session started with {sender}")
        elif isinstance(item, TextContent):
            try:
                await handle_text(ctx, sender, item.text.strip())
            except Exception as e:  # recovery path: tell the user, never go silent
                ctx.logger.error(f"engine call failed: {e}")
                await ctx.send(sender, text(f"Something failed on my side ({e}). Reply \"status\" to check again."))
        elif isinstance(item, EndSessionContent):
            ctx.logger.info(f"Session ended with {sender}")


async def handle_text(ctx: Context, sender: str, message: str):
    lower = message.lower()
    async with httpx.AsyncClient(base_url=BACKEND, timeout=20) as api:
        if "cancel" in lower or "handle it" in lower:
            task = (await api.post("/tasks", json={"source": "asi1"})).json()
            ctx.storage.set(sender, task["task_id"])
            await ctx.send(sender, text(options_message(task)))
        elif lower in {"book", "approve", "yes", "1"}:
            task_id = ctx.storage.get(sender)
            if not task_id:
                await ctx.send(sender, text("Tell me what broke first, e.g. \"My UA183 got cancelled, handle it.\""))
                return
            await api.post("/approval", json={"task_id": task_id, "approved": True, "fee_allowance_usd": FEE_ALLOWANCE_USD})
            await ctx.send(sender, text("Booked. Your guesthouse desk closes before you land, so I'm calling them now…"))
            # If ASI:One doesn't show a second message per turn, the user replies "status" instead.
            await ctx.send(sender, text(outcome_message(await wait_for_outcome(api, task_id))))
        elif lower.startswith("status"):
            task_id = ctx.storage.get(sender)
            state = (await api.get(f"/tasks/{task_id}")).json()
            msg = outcome_message(state) if state["stage"] == "resolved" else f"Still working: {state['stage']}."
            await ctx.send(sender, text(msg))
        else:
            await ctx.send(sender, text("Tell me what broke, e.g. \"My UA183 got cancelled, handle it.\""))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info(f"ack from {sender} for {msg.acknowledged_msg_id}")


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
