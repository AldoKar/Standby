"""Caller agent: places disclosed AI calls to businesses that have no API (owner: P2).

Usable on its own in ASI:One ("call this business and ask X"), and hired by the
orchestrator for $1.99 per call through the Payment Protocol.

Status: skeleton. Build it after the orchestrator's full ASI:One flow works (9 PM checkpoint).
TODO(P2):
  - Add the Payment Protocol: request $1.99 before placing the call (Stripe test mode).
  - Place the call through the engine (CALL_MODE=elevenlabs) and return the structured outcome.
  - Retry once on voicemail, then report it.
  - Business lines only; first sentence always says it is an AI and the call is recorded.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

agent = Agent(
    name="standby-caller",
    seed=os.getenv("CALLER_SEED", "standby caller dev seed, change me"),
    port=int(os.getenv("CALLER_PORT", "8002")),
    mailbox=True,
)
chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    for item in msg.content:
        if isinstance(item, TextContent):
            ctx.logger.info(f"call request from {sender}: {item.text}")
            reply = "I place calls to business lines for $1.99 each. Calling isn't wired up yet."
            await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                               content=[TextContent(type="text", text=reply)]))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
