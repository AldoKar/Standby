![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Fetch.ai agents (owner: P2)

| Agent | Name | Address | Job |
|---|---|---|---|
| Orchestrator | `standby` | `agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf` | ASI:One front door: plans within the mandate, calls the engine, reports in chat |
| Caller | `standby-caller` | _not built yet — skeleton only, see "What's left"_ | Places disclosed AI calls to business lines; paid $1.99 per call through the Payment Protocol |

Shared asi1.ai chat URL: _fill in after the first chat (see "Verify it" below)_

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

On first run the agent prints its address and an inspector link. The mailbox for
`agent1qwy…` is already connected; a new address would need connecting through that link
before ASI:One can reach it. Run both agents on the Vultr box under systemd for the demo.

## Verify it

1. Start the engine and the orchestrator as above.
2. In a fresh chat at [asi1.ai](https://asi1.ai), find the agent by description
   ("rebooks cancelled flights", "flight cancelled handle it") or by its address.
3. Type: `My UA183 got cancelled, handle it`
4. You should get the three options with two struck through and the policy reason for each.
5. Reply `approve`. You get two messages: the booking, then the call outcome with the door
   code and the ledger. The session ends on that second message.
6. `status?` at any point answers from engine state rather than from the transcript.
7. Share the chat and paste the URL into the table at the top.

Reset between runs with `curl -X POST localhost:8000/demo/reset`.

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

The engine decides money. It runs the mandate check, returns allow / ask / deny and
executes the charge; the LLM only passes the traveller's answer through and never sees card
data. Amounts quoted in chat come from the tool result, including the
`remaining_after_this_usd` the engine's ledger implies — the model is told not to do
arithmetic on money.

Per-sender state (`task_id`, pending `approval_id`, the last 6 turns) lives in
`ctx.storage`. The engine, not the transcript, is the source of truth: every turn re-reads
it through a tool.

## Checklist (Fetch requirements)

- [x] Registered on Agentverse, Chat Protocol manifest published (`AgentChatProtocol 0.3.0`)
- [x] The whole flow runs in one chat: cancelled → options → approve → book → call → result
- [x] **More than one message per user turn works** — "approve" returns the booking, then the
      call outcome, as two separate `ChatMessage`s. Verified agent-to-agent over the real
      transport; confirm the asi1.ai UI renders both when you run step 2 above.
- [x] `EndSessionContent` is sent only with the final result, never earlier
- [ ] Innovation Lab + hackathon badges and a search-style description — `readme_path` and
      `description` on the constructor do **not** publish to the Agentverse profile for a
      mailbox agent. Paste `orchestrator/README.md` into the profile's Agent Guide by hand.
- [ ] ASI:One finds the agent by plain-language query (needs a real chat to confirm)
- [x] Interactive Cards: options carousel, review card with Approve and the fee allowance,
      terminal result card — built and structurally validated. Text rides above every card
      and is what shows if ASI:One rejects one. **Needs one asi1.ai run to confirm rendering.**
- [ ] Caller agent paid through the Payment Protocol, with a retry-on-voicemail path
- [ ] Shared chat URL pasted into the table above

## Interactive Cards

Each card is a `MetadataContent` block sent alongside the `TextContent`, so a client that
cannot render cards still gets the full answer — and if ASI:One rejects a payload it
silently falls back to that same text. Nothing is lost either way.

| Card | Kind | When |
|---|---|---|
| Options | `carousel` | After `get_booking` / `search_flights`. The pick is badged **Recommended** and is the only item with a button; the two the policy ruled out carry their reason in the subtitle and no CTA, which is this surface's version of struck through. |
| Review | `review` | After `request_approval`. Flight, departure, arrival, price, budget left afterwards, fee allowance; **Approve $215** and **No, not this one**. |
| Result | `review`, terminal | When the task resolves. Room, door code, who was spoken to, fee, spent, refund pending. Not interactive. |

A button press arrives as a JSON selection string (`{"action": "approve", …}`).
`as_instruction()` turns it into the sentence the traveller would have typed, so card taps
and typed replies run down exactly the same path — which is why the text flow stays a true
fallback rather than a second code path that can rot.

Cards are chosen in Python from engine state, never by the model, so a card can't quote a
number the engine didn't produce. The first card requested in a turn wins, so a turn that
loads the booking *and* the approval still shows the carousel first.

## What's left

**Caller agent.** `caller/agent.py` is still the skeleton. Two things to settle first:
the engine has no agent-facing endpoint to start a call (raised in `NEEDS.md`), and the
installed `AgentPaymentProtocol 0.1.0` documents `skyfire` and `fet_direct` as payment
methods, with no Stripe test rail. If Stripe test mode is needed, that likely means a newer
`uagents-core` or the separate Stripe integration; otherwise the $1.99 per call should go
over `fet_direct` on testnet. **This needs a decision before building it.**
