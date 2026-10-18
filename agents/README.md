![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Fetch.ai agents (owner: P2)

| Agent | Name | Address | Job |
|---|---|---|---|
| Orchestrator | `standby` | `agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf` | ASI:One front door: plans within the mandate, calls the engine, reports in chat |
| Caller | `standby-caller` | `agent1q2480yjzfu7jv4sk7x9v2s0v7zf89mj9czpqs3sqtaypt5kyd4xkg7yge07` | Places disclosed AI calls to business lines; paid $1.99 per call through the Payment Protocol |

Shared asi1.ai chat URL (opens logged out, verified):
**https://asi1.ai/shared-chat/ab2f568d-d49e-4ec4-a279-5bb77195afbd**

That one chat evidences every Fetch requirement: discovery and use through ASI:One, the
whole flow in one conversation, and the Caller hired and paid over the Agent Payment
Protocol.

### A rendering quirk worth knowing

The agent sends the booking confirmation and the call outcome as two separate
`ChatMessage`s, about six seconds apart. asi1.ai renders this inconsistently: sometimes
two bubbles (21:39 run), sometimes merged into one **and reordered**, with the outcome
printed above the booking (23:04 run, visible in the shared chat above). Nothing to fix on
our side — both messages are sent correctly and in order, verified over the wire with
`chat_local.py`. Don't stop and retry on stage if the booking message appears to be
missing; it is in the bubble, further down.

## Versions

Pinned by `requirements.txt`, installed and tested with:

| Package | Version |
|---|---|
| `uagents` | 0.26.1 |
| `uagents-core` | 0.4.12 |
| `anthropic` | 1.15.0 |
| `httpx` | 0.28.1 |

Chat Protocol: `AgentChatProtocol 0.3.0` (`uagents_core.contrib.protocols.chat`).
Payment Protocol in this version: `AgentPaymentProtocol 0.1.0`, whose `Funds.payment_method`
documents `skyfire` and `fet_direct` — **not** Stripe. See "What's left".

## Run

The orchestrator needs the engine on `ENGINE_URL` and an Anthropic key.

```bash
# terminal 1 — the engine
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# terminal 2 — the orchestrator
cd agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python orchestrator/agent.py
```

Config comes from the repo-root `.env` (never commit it):

| Key | What it does |
|---|---|
| `AGENT_SEED` | **Required.** Decides the agent's address. Must be the workshop seed, or the agent comes up as a different address and loses its Agentverse mailbox, profile and badges. |
| `ANTHROPIC_API_KEY` | Required. |
| `ENGINE_URL` | Defaults to `http://localhost:8000`. |
| `CLAUDE_MODEL` | Defaults to `claude-sonnet-5`. Set `claude-haiku-4-5` if latency is bad. |
| `ORCHESTRATOR_PORT` | Defaults to `8001`. |
| `CALLER_ADDRESS` | The Caller's address, so the orchestrator can hire it. |
| `CALLER_LOCAL_ENDPOINT` | Set to `http://127.0.0.1:8002/submit` when both agents run on this machine: the orchestrator then reaches the Caller over loopback instead of waiting on the Agentverse mailbox. Leave it unset in deployment. |

On first run the agent prints its address and an inspector link. The mailbox for
`agent1qwy…` is already connected; a new address would need connecting through that link
before ASI:One can reach it. Run both agents on the Vultr box under systemd for the demo.

## Verify it

1. Start the engine and the orchestrator as above.
2. In a fresh chat at [asi1.ai](https://asi1.ai), find the agent by description
   ("rebooks cancelled flights", "flight cancelled handle it") or by its address.
3. Type: `@standby My UA183 got cancelled, handle it`

   **Mention the handle on every message, not just the first.** Without it ASI:One routes
   the message to your own assistant instead of the agent — it will happily invent its own
   booking plan and spin for minutes while the agent sits idle. The agent's replies name
   the handle in the ask for this reason (`ASI_HANDLE`, default `@standby`).
4. You should get the three options with two struck through and the policy reason for each.
5. Reply `@standby approve`. You get two messages. The first confirms the booking **and
   breaks the news the traveller doesn't have yet** — the guesthouse front desk closes at
   11 PM, they land at 10:40, so it's calling to hold the room. That reveal is the point
   of the demo (`docs/SPEC.md` step 5); without it the phone call appears from nowhere.
   Then: the booking, then the call outcome with the door
   code and the ledger. The session ends on that second message.
6. `status?` at any point answers from engine state rather than from the transcript.
7. Share the chat and paste the URL into the table at the top.

Reset between runs with `curl -X POST localhost:8000/demo/reset`.

### Showing the Payment Protocol

It does **not** fire in the main flow. After a booking the *engine* places the call
itself, and `hire_caller` deliberately refuses to pay for a call already in progress — so
no agent-to-agent payment happens. To show it, ask for a second call once the task has
resolved:

> `@standby call the guesthouse again and ask for a late checkout tomorrow`

That hires the Caller, pays $1.99 over the Agent Payment Protocol, places the call and
reports back — and the reply says so, in whatever words it picks that turn: *"Called Hayes
St Guesthouse — fee $1.99, covered by Standby, not you."* Agent-to-agent payments are
protocol messages, not chat content, so the narration is the only way a judge sees them.

The wording is not scripted, and deliberately so. An example sentence in the system prompt
was quotable enough that the model reproduced it on turns where `hire_caller` had never
run, telling the traveller it had hired and paid an agent that never heard from it. The
fee now comes from the tool result or is not mentioned: `fee_paid` when the Caller
actually charged, `no_fee_was_paid` when it did not.

## Tests

```bash
cd agents && python test_agents.py          # tool layer, guardrails, cards — no LLM calls
cd agents && python test_agents.py --live   # also drives Claude end to end
```

Needs the engine running. Run it before opening a PR, like `engine/test_engine.py`.

To drive the agent by hand without Agentverse or ASI:One — useful for rehearsing the demo,
and the backup if asi1.ai misbehaves on the day:

```bash
cd agents && python chat_local.py
```

It talks to the running orchestrator over the real Chat Protocol and prints the cards.

## How it works

ASI:One → Chat Protocol → orchestrator → REST → engine.

Claude (`claude-sonnet-5`, `max_tokens` 300, thinking off, system prompt in a
`cache_control` block) phrases the replies and picks the tools. Every tool is an HTTP call
to an endpoint in `contract/api.md`:

| Tool | Engine call |
|---|---|
| `get_booking` | `POST /tasks` — starts the task, returns the ranked options and the pending approval |
| `search_flights` | `GET /tasks/{id}` (falls back to `GET /flights/search`) |
| `request_approval` | `GET /tasks/{id}` → the pending spend, budget and fee allowance |
| `pay` | `POST /approval` — passes the traveller's yes/no through |
| `call_provider` | `POST /call/start` if it exists, else reports the call the engine started |
| `save_to_vault` | `POST /events` with `vault.updated` |
| `get_status` | `GET /tasks/{id}` |
| `get_ledger` | `GET /ledger` |
| `ask_live` | `POST /ask` with `show: false`: free questions answered by the engine's Claude with live FlightAware status, the Vault and the ledger. Read-only; needs `ANTHROPIC_API_KEY` (and `AEROAPI_KEY` for live flights) on the engine |

The engine decides money. It runs the mandate check, returns allow / ask / deny and
executes the charge; the LLM only passes the traveller's answer through and never sees card
data. Amounts quoted in chat come from the tool result, including the
`remaining_after_this_usd` the engine's ledger implies — the model is told not to do
arithmetic on money.

Per-sender state (`task_id`, pending `approval_id`, the last 6 turns) lives in
`ctx.storage`. The engine, not the transcript, is the source of truth: every turn re-reads
it through a tool.

**ASI:One relays one conversation from several sender addresses** — the options come back
to one address and "approve" arrives at another. Keyed on sender alone the approval lands
in an empty bucket and the agent answers "no task has started yet". `ensure_fresh()`
reconciles against the engine on every turn: a chat with no task adopts whatever task is
in flight, and a task the engine has reset away clears the transcript. The engine runs one
task at a time, which is what makes this safe — and is also why two people chatting to the
agent at once would share a trip. Fine for the demo, wrong for production.

## The Caller agent

`standby-caller` is a second agent that does one thing: phone a business that has no API
and report what was agreed. It is discoverable on its own ("call this guesthouse and hold
my room") and hired by the orchestrator.

```
orchestrator (buyer)                      caller (seller)
  --- ChatMessage: the job --------------->
  <-- RequestPayment $1.99 ----------------
  --- CommitPayment(transaction_id) ------>
  <-- CompletePayment --------------------   then places the call
  <-- ChatMessage: summary + JSON outcome -
```

Two things worth knowing:

- **The $1.99 is Standby's cost, not the traveller's.** The mandate covers airlines and
  lodging; a subcontractor is neither. Paying it from the traveller's $300 would be wrong,
  and the policy engine would deny it anyway. The orchestrator pays from its own budget,
  capped by `CALLER_MAX_USD`, and logs an `agent.hired` event so it still appears on the
  dashboard. The reply tells the traveller the fee was not theirs.
- **It will not pay twice.** If the engine already has a call in flight, `hire_caller`
  refuses before any payment is sent. That is enforced in code, not asked for in the
  prompt, because the failure costs money.

Run it alongside the orchestrator:

```bash
cd agents && python caller/agent.py          # port 8002
CALL_VOICEMAIL_FIRST=true python caller/agent.py   # force the retry path for a demo
```

## Checklist (Fetch requirements)

- [x] Registered on Agentverse, Chat Protocol manifest published (`AgentChatProtocol 0.3.0`)
- [x] The whole flow runs in one chat: cancelled → options → approve → book → call →
      result. **Confirmed on asi1.ai 2026-10-17 21:39.**
- [x] **More than one message per user turn works, confirmed in the asi1.ai UI** — one
      `@standby approve` produced two separate bubbles: the booking, then the call outcome
      with the door code and ledger. This was the open question from the plan's 6 PM
      checkpoint.
- [x] `EndSessionContent` is sent only with the final result, never earlier
- [ ] Innovation Lab + hackathon badges and a search-style description — `readme_path` and
      `description` on the constructor do **not** publish to the Agentverse profile for a
      mailbox agent. Paste `orchestrator/README.md` into the profile's Agent Guide by hand.
- [x] Found and driven through ASI:One by `@standby` handle
- [x] Found by *plain-language* query — **tested 2026-10-17 22:48: a message with no
      handle never reaches the agent.** ASI:One routes un-mentioned messages to the
      user's own assistant by default ("Messages without an @mention are routed to your
      personal AI"), which answered instead and asked for flight details it does not
      have. This is platform routing, not an agent fault: with `@standby` the agent is
      reachable and the whole flow completes, which is what the hackpack asks for
      ("discoverable and functional through ASI:One", "primary workflows complete within
      ASI:One conversations"). **Demo with the handle, every message.**
- [ ] Interactive Cards: all three built and structurally validated against the spec, but
      **asi1.ai renders the text, not the cards** (tested 2026-10-17 with a direct
      `@standby` mention). The documented behaviour is a silent fallback to text, which is
      what we see. Cards stay attached — they cost nothing and lose nothing. See
      "Interactive Cards" below for what was tried.
- [x] Caller agent paid through the Payment Protocol, with a retry-on-voicemail path —
      `AgentPaymentProtocol 0.1.0`, Caller is the seller, orchestrator the buyer. Verified
      agent-to-agent: hire → RequestPayment $1.99 → CommitPayment → CompletePayment →
      call → outcome. Retry verified with `CALL_VOICEMAIL_FIRST=true`.
- [ ] Connect the Caller's Agentverse mailbox so ASI:One can reach it directly
- [ ] Share the chat publicly and confirm the URL above opens for someone logged out

## Interactive Cards

Each card is a `MetadataContent` block sent alongside the `TextContent`, so a client that
cannot render cards still gets the full answer — and if ASI:One rejects a payload it
silently falls back to that same text. Nothing is lost either way.

| Card | Kind | When |
|---|---|---|
| Options | `carousel` | After `get_booking` / `search_flights`. The pick is badged **Recommended** and is the only item with a button; the two the policy ruled out carry their reason in the subtitle and no CTA, which is this surface's version of struck through. |
| Review | `review` | After `request_approval`. Flight, departure, arrival, price, budget left afterwards, fee allowance; **Approve $215** and **No, not this one**. |
| Result | `review`, terminal | When the task resolves. Room, door code, who was spoken to, fee, spent, refund pending. Not interactive. |

**Status: asi1.ai did not render them.** Both a planner-routed and a direct `@standby`
message came back as plain text. Fetch's spec says an unrenderable card degrades silently
to the accompanying text, which matches what we saw, so this may be a payload the UI
rejects or simply a surface that does not draw cards yet. The text path is unaffected and
is what the demo shows. Left attached rather than ripped out: zero cost if unrendered,
and it works the moment the surface supports it.

A button press arrives as a JSON selection string (`{"action": "approve", …}`).
`as_instruction()` turns it into the sentence the traveller would have typed, so card taps
and typed replies run down exactly the same path — which is why the text flow stays a true
fallback rather than a second code path that can rot.

Cards are chosen in Python from engine state, never by the model, so a card can't quote a
number the engine didn't produce. The first card requested in a turn wins, so a turn that
loads the booking *and* the approval still shows the carousel first.

## What's left

**Caller settlement is simulated.** The Payment Protocol handshake is real and runs over
the wire, but no FET actually moves: `AgentPaymentProtocol 0.1.0` offers `skyfire` and
`fet_direct` only — **there is no Stripe test rail** — and these agents hold no funds
(both log "I do not have enough funds to register on Almanac contract"). Making it settle
for real means funding the wallets and constructing the agents with `network="testnet"`.
The pricing, the handshake and the refusal path are all genuine; the transfer is a
reference string.

**The Caller's mailbox still has to be connected** through its inspector link before
ASI:One can talk to it directly. Until then the Caller answers only the orchestrator,
which reaches it over loopback.

It used to advertise that loopback endpoint to the Almanac, which was worse than it
sounds. uAgents takes a mailbox *or* an endpoint, never both (`uagents/config.py:75-99`):
passing `endpoint=` dropped the mailbox entirely, started no mailbox client, and published
`http://127.0.0.1:8002/submit` as the Caller's one public address — so every sender,
ASI:One included, was told to deliver to its own machine. The Almanac record is global and
last-writer-wins, so a single local run was enough to break it for everyone, invisibly
from this laptop. The Caller is now `mailbox=True` only, and the local shortcut lives on
the sender instead: set `CALLER_LOCAL_ENDPOINT` on the orchestrator and its resolver tries
loopback first, falling back to the mailbox when nothing answers there.
