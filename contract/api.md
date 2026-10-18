# API

Base URL: the engine (locally `http://localhost:8000`). All bodies are JSON, and CORS is open.

| Method and path | Called by | Body → response |
|---|---|---|
| `GET /events` | Glasses, dashboard | SSE stream (see `events.md`) |
| `GET /state` | Anyone (debugging) | Full state snapshot |
| `POST /input` | Glasses | `{"gesture", "screen_id"?}`, gesture is `press`, `hold` or `swipe_down` → `{"handled", "stage"}` |
| `POST /simulate/cancel` | Dashboard | Starts the flow, same as a press on the Ready screen |
| `POST /demo/reset` | Dashboard | Back to the Ready screen |
| `POST /tasks` | Orchestrator agent (ASI:One) | `{"source": "asi1"}` → `{task_id, stage, options, pick, approval_id}`. Starts the flow and goes straight to the booking approval |
| `GET /tasks/{task_id}` | Orchestrator agent | → `{task_id, stage, options, pick, approvals, outcome, ledger}` |
| `POST /approval` | Orchestrator agent, dashboard | `{"approval_id"?, "task_id"?, "approved", "fee_allowance_usd"?}` → the approval. Without an id it answers the latest pending approval |
| `POST /call/approval` | Voice agent tool `request_approval` | `{"amount", "reason", "kind"?, "merchant"?, "mcc"?}` → `{approval_id, status}`; status is pending, approved or denied |
| `GET /call/approval/{approval_id}` | Voice agent tool `check_approval` | `?wait_s=8` (optional, capped at 12) holds the request until the wearer answers → `{approval_id, status}`; status is pending, approved, rejected or denied |
| `POST /call/completed` | Post-call adapter for the voice agent | `{"held", "door_code"?, "contact"?, "fee_usd"?, "transcript_url"?, "verified"?, "transcript"?}`. With `transcript` ("Agent: ...
Clerk: ..."), Claude checks the outcome against it; a door code reaches the glasses only when verified |
| `POST /call/webhook` | ElevenLabs post-call webhook | ElevenLabs' own `post_call_transcription` / `call_initiation_failure` payload, signed with `ELEVENLABS_WEBHOOK_SECRET` (401 otherwise). The engine builds the transcript, has Claude check it and finishes the task. Needs `task_id` in the call's dynamic variables (the engine sets it) |
| `POST /merchant/payment-request` | Mock merchant | `{"merchant", "amount", "mcc"}` → paid, or refused by the mandate |
| `GET /ledger` | Dashboard | Mandate, spends, refunds, consent records, denied attempts, remaining budget |
| `POST /mandate` | Phone, after the passkey sign-in | Mandate fields to override → the mandate |
| `GET /flights/search` | Anyone | Mock options, ranked by the policy engine |
| `GET /tests` | Dashboard | Last `python test_engine.py` run: `{ran_at, passed, total, cases: [{name, passed, detail}]}`; 404 until tests have run |
| `GET /` | Browser | The dashboard |
| `GET /dashboard/{file}` | Browser | Other files in `dashboard/`, e.g. `recorded-call.mp3` |

## Rules

- Spending decisions happen only in `backend/app/policy.py`, never in an LLM prompt.
- To change the contract (an event, a field, an endpoint), open a PR that edits this folder, and tell the team in chat.
