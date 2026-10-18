import os
from datetime import datetime
from uuid import uuid4

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
from uagents import Context, Protocol, Agent
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)
 
 
### Example Expert Assistant
 
## This chat example is a barebones example of how you can create a simple chat agent
## and connect to agentverse. In this example we will be prompting the ASI:One model to
## answer questions on a specific subject only. This acts as a simple placeholder for
## a more complete agentic system.
##
 
MODEL = "claude-opus-5"

SYSTEM_PROMPT = "You are Standby's travel agent. Reply in at most 3 short lines."

# Reads ANTHROPIC_API_KEY from the environment.
client = Anthropic()

agent = Agent(
    name="ASI uAgent",
    seed=os.getenv("AGENT_SEED", "REDACTED_AGENT_SEED"),
    port=8001,
    mailbox=True,
    publish_agent_details=True,
)
 
# We create a new protocol which is compatible with the chat protocol spec. This ensures
# compatibility between agents
protocol = Protocol(spec=chat_protocol_spec)
 
 
# We define the handler for the chat messages that are sent to your agent
@protocol.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    # send the acknowledgement for receiving the message
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(), acknowledged_msg_id=msg.msg_id),
    )
 
    # collect up all the text chunks
    text = ''
    for item in msg.content:
        if isinstance(item, TextContent):
            text += item.text
 
    # query the model based on the user question
    response = 'I am afraid something went wrong and I am unable to answer your question at the moment'
    try:
        r = client.messages.create(
            model=MODEL,
            # Thinking is on by default and shares this budget with the reply,
            # so keep headroom even though the HUD copy itself is short.
            max_tokens=2048,
            # Short, latency-sensitive replies: spend as few thinking tokens as possible.
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )

        # content is a list of blocks (thinking, text, ...) — never index [0] blindly.
        response = "".join(b.text for b in r.content if b.type == "text")
    except:
        ctx.logger.exception('Error querying model')
 
    # send the response back to the user
    await ctx.send(sender, ChatMessage(
        timestamp=datetime.utcnow(),
        msg_id=uuid4(),
        content=[
            # we send the contents back in the chat message
            TextContent(type="text", text=response),
            # we also signal that the session is over, this also informs the user that we are not recording any of the
            # previous history of messages.
            EndSessionContent(type="end-session"),
        ]
    ))
 
 
@protocol.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    # we are not interested in the acknowledgements for this example, but they can be useful to
    # implement read receipts, for example.
    pass
 
 
# attach the protocol to the agent
agent.include(protocol, publish_manifest=True)
 
if __name__ == "__main__":
    agent.run()
 