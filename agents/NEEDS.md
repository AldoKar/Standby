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

---

# Defects found outside `agents/`

Found while verifying the merged tree on Oct 18. P2 owns `agents/` only, so none of these
are fixed here. Every line number below was re-checked against the file. Ordered by what
a judge would actually notice.

## P4 — `dashboard/`

1. **"Handle It" is still on screen.** `dashboard/index.html:6` (`<title>`) and `:96`
   (`<h1>`). The project is Standby everywhere else; this is the heading on the projected
   demo screen.
2. **Three documented events have no panel.** `dashboard/index.html:218-313` handles 14
   event types; `vault.updated`, `task.resolved` and `voice.heard` have no branch. They
   still reach the Activity feed as raw JSON, so nothing is lost — but **there is no Vault
   panel at all** (`grep vault dashboard/index.html` → nothing), and `docs/SPEC.md:16,20,32`
   treats the Vault as a judged feature. `task.resolved` means the demo never shows as
   finished.
3. **"Simulate cancellation" fails silently mid-flow.** `dashboard/index.html:481` discards
   the response; `engine/app/main.py:452-454` returns `{handled: false}` when a task is
   already running. A judge pressing it twice gets no feedback. `g2-app/src/App.tsx:176-180`
   already does this right ("The demo is already running. Reset it first.") — lift that.

## P3 — `g2-app/`

4. **A failed call looks identical to a successful one on the lens.** `g2-app/src/hud/
   screens.ts` has no `STYLES` entry for `not_held` or `call_failed`, so both get
   `DEFAULT_STYLE` — no alert icon, no alert border. The compensating heuristic at
   `screens.ts:84-88` tests `screen_id === 'resolved'`, which the engine no longer sends
   for a failure (`engine/app/main.py:324` sends `not_held`, `:283` sends `call_failed`,
   both documented at `contract/events.md:46`), so that branch is dead code. The
   `TODO(P1)` at `screens.ts:85` asking for exactly this screen_id is already shipped.
5. **`vault.updated` type disagrees with the contract.** `g2-app/src/engine/types.ts:43`
   declares `{type, flight?}`; the engine publishes `{type, id, title}`
   (`engine/app/main.py:84`, `contract/events.md:22`). No runtime break — `eventText.ts:52`
   only reads `.type`. Same file: `payment.executed` omits `signature`,
   `call.completed.outcome` omits `verified`/`summary`/`issues`.
6. **Stale notes.** `g2-app/README.md:74-76` — three of the four "notes for other owners"
   were fixed long ago (`/input` does enforce `screen_id`; failures do use `not_held`;
   `contract/api.md:43` does say `engine/app/policy.py`).

## P1 — `engine/`

7. **Glasses voice is dead: no `OPENROUTER_API_KEY` in `engine/.env`.** It is in
   `engine/.env.example:19`. `engine/app/__init__.py:7` loads `engine/.env`, so that is the
   live config. Audio from the glasses returns
   `"voice not configured: no OPENROUTER_API_KEY"` (`voice.py:92` → `main.py:431-433`), and
   even typed transcripts fall back to the ≤4-word keyword path only (`voice.py:106-108`).
   The glasses degrade honestly — `listener.ts:50` flashes "VOICE OFF" — so this is a
   missing key, not a code bug. `test_engine.py:270` deliberately pops the key, so tests
   will never catch it.
8. **Merged-import artifact.** `engine/app/main.py:25-26`:
   ```python
   from . import call, policy, verify, voice
   from . import call, policy, tap, verify
   ```
   Harmless at runtime, but **both lines are load-bearing** — line 25 is the only source of
   `voice`, line 26 the only source of `tap`. Merge them into one line; do not delete
   either.
9. **"Handle It" in the OpenAPI title.** `engine/app/main.py:37` — visible at `/docs`.
10. **Dead/misleading keys in `engine/.env`.** `AGENT_MODE`, `FLIGHTS_MODE` and
    `DUFFEL_TOKEN` are read by no code on `main` (they belong to the unmerged
    `p1-real-agent` branch), and `FLIGHTS_MODE=mock` implies a live mode that
    `GET /flights/search` does not have. The comment above `ANTHROPIC_API_KEY` says
    "Gemini"; `app/verify.py` uses Claude. `engine/.env.example:15` has it right.

## `contract/` — by PR, per AGENTS.md

11. **`POST /simulate/cancel` is undocumented** yet both `dashboard/index.html:481` and
    `g2-app/src/engine/client.ts:88` depend on it.
12. **`POST /events` is undocumented** (`engine/app/main.py:355-357`). It injects an
    arbitrary event into the SSE stream, unauthenticated, with CORS open to `*`. This is
    how P2's `agent.hired` reaches the dashboard, so P2 depends on it — but it should be a
    deliberate contract entry rather than an accident.
13. **`agent.hired` is not in `contract/events.md`.** P2 publishes it from
    `agents/orchestrator/agent.py:892`. Nothing consumes it yet; adding the row is the
    cheap fix.
14. **`GET /tasks/{task_id}` under-documents its response.** `contract/api.md:13` lists
    seven fields; `snapshot()` (`engine/app/main.py:123-135`) also returns `screen`,
    `vault` and `call_mode`.
15. **`GET /dashboard/{file}` is not a decorated route** — it is
    `app.mount(...)` at `engine/app/main.py:653`. Noted so nobody greps for
    `@app.get("/dashboard")` and concludes it is missing.

## Checked and found correct

`engine/app/policy.py` (mandate, MCC, budget, the NaN guard), `engine/app/tap.py`
(RFC 9421 signing, nonce replay, expiry), `engine/app/call.py`, `engine/app/verify.py`
— including `MODEL = "claude-opus-5-5"`, which looks like a typo but is a real current
model and returns a correct verified outcome against the live API. `contract/mock-data.json`
is internally consistent. The voice-intent table in `contract/api.md:34-39` matches both
`engine/app/voice.py` and `g2-app/src/hud/screens.ts`. No secret is tracked in git.
