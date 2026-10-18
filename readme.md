# Standby

> **Most AI assistants stop when there isn't an API. Standby picks up the phone.**

Standby is an AI travel agent that lives on your **Even G2** glasses. It books your trip, guides you at the airport and, when something goes wrong, fixes it — searching alternatives, asking for your approval with a single tap, paying securely, and **calling the airline on your behalf** when there's no API.

Built at the **LA Hacks AI Hackathon 2026** (Oct 17–18).

**Tracks:** Even Realities · Fetch.ai · Visa · MLH ElevenLabs · MLH Vultr

---

## Table of contents

1. [How it works](#how-it-works)
2. [Architecture](#architecture)
3. [Repository structure](#repository-structure)
4. [Shared contract](#shared-contract) ← **read this before writing code**
5. [Demo event sequence](#demo-event-sequence)
6. [Mock data](#mock-data)
7. [Guardrails](#guardrails)
8. [Getting started](#getting-started)
9. [Install and run on G2](#install-and-run-on-g2)
10. [Team](#team)

---

## How it works

A trip in three acts, powered by one engine: **search → approve with a tap → pay → save**.

| Act | What the user experiences |
|---|---|
| **1. Book** | "Get me to SF tomorrow before 10 PM, max $250." The agent compares flights and shows the best one on the HUD. Tap → paid with Visa → boarding pass saved to the Vault. |
| **2. Guide** | HUD alerts at the airport: `Gate changed: 52 → 61`, `Boarding in 20 min`. |
| **3. Resolve** | Flight cancelled → the alert appears on the HUD → tap → the agent finds an alternative → tap to approve → it pays, **calls the airline** and confirms → `✓ Rebooked`. |

---

## Architecture

```
G2 glasses (mic + HUD + tap)
        ⇅  Bluetooth
Even Hub app (WebView on the phone)
        ⇅  HTTPS / SSE
FastAPI backend (Vultr) ──► Web dashboard (activity feed + HUD mirror)
  · Guardrails ($250 limit, approval required)
  · Event bus (SSE)
  · Vault (Supabase)
        ⇅  REST
Standby Agent (Agentverse + Claude)  ◄── ASI:One (chat)
        ▲  ctx.send
Monitor Agent (Agentverse, reactive)
        │
Tools: Vault · Flights · Visa payment · ElevenLabs ──☎──► Airline (simulated)
```

**Principles**

- The glasses are only **display, microphone and tap**. No business logic runs there.
- The **brain lives on Fetch.ai**: the Standby Agent plans and acts; the Monitor Agent watches flights.
- The **backend is the bridge**: every component talks to it, and it broadcasts events to everyone.
- **Sensitive rules live in code**, never in the LLM.

---

## Repository structure

```
handle-it/
├── backend/          # FastAPI: events, Vault, guardrails, payments, simulators
├── agents/           # uAgents: handle_it_agent.py, monitor_agent.py
├── glasses/          # Even Hub app (TypeScript, based on the `asr` template)
├── dashboard/        # Next.js: upload, activity feed, HUD mirror, demo controls
├── voice/            # ElevenLabs agent configs and prompts (caller + airline)
├── contracts/        # Shared types: events.py (Pydantic) and events.ts
└── README.md
```

---

## Shared contract

> **Rule:** nobody renames an event, field or endpoint without telling the whole team.

### Event envelope

Every event, in both directions, has this shape:

```json
{
  "id": "evt_01",
  "type": "approval.requested",
  "task_id": "task_42",
  "ts": "2026-10-17T21:05:00Z",
  "data": { }
}
```

- `type` — one of the events below.
- `task_id` — groups all events of one trip action (booking or resolution). `null` for passive alerts.
- `data` — the payload for that event type.

### Events

| Type | Emitted by | `data` |
|---|---|---|
| `trip.requested` | backend | `{origin, dest, deadline, max_price}` |
| `task.started` | agent | `{kind: "book" \| "resolve"}` |
| `option.found` | agent | `{options: [Option], chosen: "UA927", rejected: [{flight, reason}]}` |
| `approval.requested` | agent | `{flight, departure, arrival, price, reason}` |
| `approval.granted` | backend | `{}` |
| `approval.rejected` | backend | `{}` |
| `payment.executed` | agent | `{amount, currency: "USD", method: "visa_token", reference}` |
| `flight.booked` | agent | `{flight, departure, arrival, gate, price}` |
| `gate.changed` | monitor | `{flight, old_gate, new_gate}` |
| `boarding.soon` | monitor | `{flight, gate, minutes}` |
| `flight.cancelled` | monitor | `{flight, route}` |
| `call.started` | agent | `{provider: "United"}` |
| `call.completed` | agent | `{confirmation, summary}` |
| `task.resolved` | agent | `{new_flight, departure, arrival, gate}` |
| `task.failed` | agent | `{reason}` |
| `vault.updated` | backend | `{item_type: "boarding_pass" \| "receipt" \| "call_transcript"}` |

**Option**

```json
{ "flight": "UA927", "airline": "United", "origin": "LAX", "dest": "SFO",
  "departure": "19:15", "arrival": "20:40", "price": 215, "refundable": true }
```

### HUD text per event

The glasses app maps events to screens. Max 3 lines.

| Event | HUD |
|---|---|
| `approval.requested` (book) | `UA183 · 6:10 PM` / `$189` / `Tap to buy` |
| `flight.cancelled` | `UA183 CANCELLED` / `Want me to fix it?` / `Tap = yes` |
| `approval.requested` (resolve) | `UA927 · 8:40 PM` / `$215` / `Tap to approve` |
| `call.started` | `☎ Calling United` |
| `gate.changed` | `Gate changed` / `52 → 61` |
| `boarding.soon` | `Boarding in 20 min` / `Gate 61` |
| `task.resolved` | `✓ Rebooked` / `UA927 · 8:40 PM` / `Gate 61` |

Tap = approve / yes · Double tap = reject / no.

### Backend endpoints

| Method | Path | Body | Used by |
|---|---|---|---|
| `GET` | `/events` | — (SSE stream of envelopes) | glasses, dashboard |
| `POST` | `/events` | envelope | agents |
| `POST` | `/approval` | `{task_id, approved: bool}` | glasses, dashboard |
| `POST` | `/accept-alert` | `{task_id?}` (user said "yes, fix it") | glasses |
| `POST` | `/voice` | audio file (multipart) | glasses |
| `POST` | `/trip/request` | `{origin, dest, deadline, max_price}` | dashboard, agent |
| `POST` | `/vault/upload` | file (multipart) | dashboard |
| `GET` | `/vault/booking` | `?user_id=` | agent |
| `POST` | `/vault/items` | `{type, data, file_url?}` | agent |
| `GET` | `/flights/search` | `?origin&dest&deadline&max_price` | agent |
| `POST` | `/pay` | `{task_id, amount, merchant}` | agent (guardrail-checked) |
| `POST` | `/simulate/gate` | `{}` | dashboard |
| `POST` | `/simulate/boarding` | `{}` | dashboard |
| `POST` | `/simulate/cancel` | `{}` | dashboard |
| `POST` | `/demo/reset` | `{}` | dashboard |
| `GET` | `/health` | — | everyone |

### Standby Agent tools

| Tool | Input | Output |
|---|---|---|
| `get_booking` | `{user_id}` | `{flight, origin, dest, date, departure, arrival, gate, pnr}` |
| `search_flights` | `{origin, dest, deadline, max_price}` | `{options: [Option]}` |
| `request_approval` | `{task_id, option, reason}` | `{approved: bool}` (blocks until tap) |
| `pay` | `{task_id, amount, merchant}` | `{reference}` or error from guardrails |
| `call_provider` | `{provider, goal, context}` | `{confirmation, new_flight, transcript}` |
| `save_to_vault` | `{type, data}` | `{id}` |

### Agent ↔ backend

- **Backend → Standby Agent:** `POST {AGENT_URL}/task` (uAgents `@agent.on_rest_post`) with `{task_id, kind: "book" | "resolve", user_id, input}`.
- **Agent → backend:** `POST {BACKEND_URL}/events` with an envelope, for every step.
- **Monitor → Standby Agent:** native Fetch message (`ctx.send`) `FlightAlert{flight, status}`.

---

## Demo event sequence

**Act 1 — Book**
```
trip.requested → task.started{book} → option.found → approval.requested
  → [tap] approval.granted → payment.executed → flight.booked → vault.updated
```

**Act 2 — Guide**
```
gate.changed → boarding.soon
```

**Act 3 — Resolve**
```
flight.cancelled → [tap] task.started{resolve} → option.found → approval.requested
  → [tap] approval.granted → payment.executed → call.started → call.completed
  → task.resolved → vault.updated
```

If the user rejects: `approval.rejected` → the agent emits `option.found` with the next option → new `approval.requested`.

---

## Mock data

**Booking (Act 1 result / Act 3 starting point)**

```json
{ "flight": "UA183", "airline": "United", "origin": "LAX", "dest": "SFO",
  "date": "2026-10-18", "departure": "18:10", "arrival": "19:35",
  "gate": "52", "pnr": "ABC123", "price": 189 }
```

**Alternatives after cancellation**

| Flight | Departure | Arrival | Price | Result |
|---|---|---|---|---|
| DL412 | 19:00 | 20:20 | $340 | Rejected — over $250 budget |
| AS1098 | 21:30 | 22:55 | $165 | Rejected — arrives after 10 PM |
| **UA927** | **19:15** | **20:40** | **$215** | **Chosen** |

**Monitor triggers**
- `/simulate/gate`: gate 52 → 61
- `/simulate/boarding`: 20 minutes
- `/simulate/cancel`: UA183 → `CANCELLED`

`/demo/reset` restores all of the above to the initial state.

---

## Guardrails

Enforced in `backend/guardrails.py`, never by the LLM:

- **Max $250** per purchase.
- **No payment without a matching `approval.granted`** for the same `task_id`.
- **The LLM never sees card data.** Payments use a tokenized credential stored server-side.
- Allowed actions only: book, rebook, call. No cabin upgrades.
- The voice agent always **identifies itself as an AI assistant** acting on the user's behalf.

---

## Getting started

### Environment variables

```bash
# backend/.env
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
ELEVENLABS_PHONE_NUMBER_ID=
AIRLINE_PHONE_NUMBER=
VISA_API_KEY=            # if sandbox is available
AGENT_URL=               # Standby Agent REST endpoint
STT_API_KEY=             # speech-to-text provider

# agents/.env
ANTHROPIC_API_KEY=
BACKEND_URL=
AGENT_SEED=
MONITOR_SEED=

# glasses/.env and dashboard/.env
BACKEND_URL=
```

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Agents

```bash
cd agents
pip install uagents anthropic httpx
python handle_it_agent.py
python monitor_agent.py
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
```

### Glasses (local testing)

```bash
cd glasses
npm install
npm run dev
# Generate a QR with the laptop's LAN IP (not localhost) and scan it in the Even Realities app
```

---

## Install and run on G2

> Required for the Even Realities track.

**Even Hub app name:** `Standby`

1. Install the **Even Realities** app on your phone and sign in.
2. Pair your G2 and update its firmware.
3. In the Even Realities app go to **Me → Beta tester** and install **Standby**.
4. Open Standby on the glasses. It connects to our hosted backend automatically; no API keys are needed to test.
5. From the dashboard (`<DASHBOARD_URL>`), press **Simulate cancellation** and follow the HUD.

**Controls:** tap = approve · double tap = reject / back.

To build your own copy, set `BACKEND_URL` in `glasses/.env`, then build and package the `.ehpk` following the [Even Hub packaging guide](https://hub.evenrealities.com/docs/ship/packaging).

---

## Team

| Role | Owner |
|---|---|
| Backend · Vault · guardrails · payments | Roberto Ochoa Cuevas |
| Fetch.ai agents | _TBD_ |
| G2 glasses app | _TBD_ |
| Voice (ElevenLabs) · dashboard | _TBD_ |