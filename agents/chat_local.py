"""Talk to the running Standby orchestrator from your terminal, over the real Chat
Protocol — no Agentverse, no ASI:One. Use it to rehearse the demo, and as the backup if
asi1.ai misbehaves on the day.

    cd agents && python chat_local.py

Needs the engine and the orchestrator already running. Type 'reset' to reset the engine,
'quit' to leave. Cards are summarised in the margin; the text above them is what a client
without card support would show.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import httpx
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

ORCHESTRATOR = os.getenv(
    "ORCHESTRATOR_ADDRESS",
    "agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf",
)
ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8000").rstrip("/")
PORT = int(os.getenv("CHAT_LOCAL_PORT", "8099"))

GREEN, DIM, MAGENTA, YELLOW, RESET = "\033[32m", "\033[90m", "\033[35m", "\033[33m", "\033[0m"

client = Agent(
    name="chat-local",
    seed=os.getenv("CHAT_LOCAL_SEED", "standby local chat client, dev only"),
    port=PORT,
    mailbox=False,
    publish_agent_details=False,
    endpoint=[f"http://127.0.0.1:{PORT}/submit"],
)
proto = Protocol(spec=chat_protocol_spec)
first = True


async def prompt_loop(ctx: Context) -> None:
    global first
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":  # stdin closed (piped input ran out, or ctrl-D)
            await asyncio.sleep(25)  # let any in-flight replies land, then go
            os._exit(0)
        text = line.strip()
        if not text:
            continue
        if text.lower() in ("quit", "exit"):
            os._exit(0)
        if text.lower() == "reset":
            async with httpx.AsyncClient(base_url=ENGINE_URL) as h:
                await h.post("/demo/reset")
            print(f"{YELLOW}engine reset{RESET}\n> ", end="", flush=True)
            continue
        content: list = [TextContent(type="text", text=text)]
        if first:
            content.insert(0, StartSessionContent(type="start-session"))
            first = False
        await ctx.send(ORCHESTRATOR, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content))


@client.on_event("startup")
async def start(ctx: Context):
    print(f"{DIM}talking to {ORCHESTRATOR[:24]}… via {ENGINE_URL}")
    print(f"try: My UA183 got cancelled, handle it   ('reset' resets the engine, 'quit' exits){RESET}")
    print("> ", end="", flush=True)
    asyncio.create_task(prompt_loop(ctx))


@proto.on_message(ChatMessage)
async def on_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    for item in msg.content:
        if isinstance(item, TextContent):
            print(f"\n{GREEN}{item.text}{RESET}")
        elif isinstance(item, MetadataContent):
            m = item.metadata
            payload = json.loads(m["card_payload"])
            entries = payload.get("items") or payload.get("summary_rows") or []
            print(f"{MAGENTA}  ┌ card · {m['card_kind']} · {payload.get('title')}"
                  f"{' · terminal' if m.get('is_terminal') else ''}{RESET}")
            for e in entries:
                if "title" in e:  # carousel item
                    cta = e.get("primary_cta", {}).get("label")
                    print(f"{MAGENTA}  │ {e['title']:<22}{e.get('secondary_text',''):>6}"
                          f"  {DIM}{e.get('subtitle','')}{RESET}"
                          + (f"{MAGENTA}  [{cta}]{RESET}" if cta else f"{DIM}  (ruled out){RESET}"))
                else:            # review row
                    print(f"{MAGENTA}  │ {e['label']:<20} {e['value']}{RESET}")
            for key in ("approve_cta", "reject_cta"):
                if payload.get(key):
                    print(f"{MAGENTA}  │ [{payload[key]['label']}] "
                          f"{DIM}→ send: {json.dumps(payload[key]['selection'])}{RESET}")
            print(f"{MAGENTA}  └{RESET}")
        elif isinstance(item, EndSessionContent):
            print(f"{YELLOW}  (session ended){RESET}")
    print("> ", end="", flush=True)


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


client.include(proto, publish_manifest=False)

if __name__ == "__main__":
    client.run()
