# What P2 needs from other folders

Nothing here is urgent — the orchestrator works without all of it. Each item says what
P2 does in the meantime.

## From P1 (engine)

### 1. `POST /call/start` — an agent-facing way to start the call

`contract/api.md` has no endpoint that lets an agent start a phone call. Today the engine
starts it itself inside `after_booking()`, which works for the ASI:One flow but leaves the
Caller agent (paid $1.99 per call through the Payment Protocol) with nothing to call.

Proposed, matching the existing style:

| Method and path | Called by | Body → response |
|---|---|---|
| `POST /call/start` | Caller agent, orchestrator | `{"task_id", "purpose", "to"?}` → `{"call_id", "mode", "started"}` |

Behaviour: start the call for that task the same way `after_booking()` does, and return
immediately. Publishes `call.started` as it already does. If the task is not at a stage
where a call makes sense, 409 rather than starting one.

**Meanwhile:** the Caller agent tries `POST /call/start` first and falls back to a mock
clerk built from `contract/mock-data.json`, reporting the outcome to whoever hired it. It
only posts `/call/completed` when the engine is actually at the `calling` or `fee` stage,
so a standalone call can never finish somebody else's task. Confirmed today: the endpoint
returns 404, so every call currently takes the mock path.

### 2. `GET /tasks/{task_id}` returns the whole snapshot

Not a bug, just a note: it returns the same shape as `GET /state`, including `screen` and
`call_mode`. P2 only reads `stage`, `options`, `pick`, `approvals`, `outcome` and `ledger`.
No change needed — recording it so the fields P2 depends on are known before anyone
trims the payload.

## From P4 (voice)

Nothing yet. When the Caller agent places real calls, it will need the ElevenLabs agent to
accept a `purpose` dynamic variable so one agent can serve more than the guesthouse script.
