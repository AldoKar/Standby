# Standby — LA Hacks AI Hackathon Plan

> **Most AI assistants stop when there isn't an API. Standby picks up the phone.**

Deadline: **Sunday, October 18, 12:00 PM**. Deliverables: Devpost + `.ehpk` uploaded as a **Beta** build on Even Hub.

---

## 1. The idea

An AI agent that **travels with you through the whole trip**: it books for you, guides you at the airport and, when something goes wrong, fixes it — even when the fix requires talking to a human on the phone.

> "Standby is with you for the whole trip: it books, it guides you, and when something goes wrong, it fixes it — even if it has to pick up the phone."

The user is wearing Even G2 glasses. **One engine** (search → approve with a tap → pay → save) powers every stage; only the moment changes.

### The 3 acts of a trip

| Act | What happens | What we build |
|---|---|---|
| **1. Before: book** | "Get me to SF tomorrow before 10 PM, max $250." The agent searches, compares, proposes. Tap → pays with Visa → boarding pass saved to the Vault. | Reuses `search_flights` + approval + payment. |
| **2. During: guide** | HUD: `Gate changed: 52 → 61` · `Boarding in 20 min`. | Just new events from the Monitor Agent. |
| **3. When things go wrong: resolve** | Cancellation → alternative → tap → payment → call → rebooked. **Hero moment.** | The core flow. |

**Priority:** Act 3 works perfectly first. Act 1 reuses the same pieces; Act 2 is a couple of events. If time runs out, the demo starts with the boarding pass already in the Vault.

### Features

1. **Book for you.** Say where and by when; the agent compares and proposes the best option.
2. **Pay securely.** Visa payment with a tokenized credential; the agent never sees your card.
3. **Store your travel documents.** The boarding pass lives in the Vault and the app understands which flight it is.
4. **Guide you at the airport.** Gate changes and boarding alerts on your glasses.
5. **Detect problems for you.** If your flight is cancelled, you get an alert on your glasses automatically.
6. **Ask for help by voice.** Say "Handle it" — no need to explain anything else.
7. **Find the best alternative.** Picks the flight that arrives on time and fits your budget.
8. **Approve with a tap.** It never spends without your permission.
9. **Call on your behalf.** If there's no API, the agent calls the airline and negotiates the change.
10. **Save the outcome.** New boarding pass, confirmation and call transcript stored in the Vault.

### Target tracks

| Track | Why it fits |
|---|---|
| **Even Realities (G2)** | Suggested Travel category. Information in front of your eyes exactly when you need it. The judge approves a payment with a tap. |
| **Fetch.ai** | Agents on Agentverse that turn user intent into executable outcomes. Two agents with clear roles that talk to each other. |
| **Visa** | Covers the full purchase lifecycle: discovery, decision, payment and post-purchase. An agent that buys with a tokenized credential, a spending limit and explicit approval. |
| **MLH ElevenLabs** | The outbound call is a core part of the flow. |
| **MLH Vultr** | The backend is deployed there (it needs to be public anyway). |

**Confirmed with Even:** the financial-app restriction only applies to public store release; for the hackathon (Beta) we can include payments.

**To confirm with Visa:** Visa isn't listed in the Devpost prizes. Ask at their table whether there's a track, its criteria, and which APIs/sandbox they provide (e.g. Visa Intelligent Commerce / tokenized agent payments). Without a sandbox, payment is simulated in the backend as its own step (`payment.executed`).

---

## 2. Architecture

```
G2 glasses (mic + HUD + tap)
        ⇅  Bluetooth
Even Hub app (WebView on the phone)
        ⇅  HTTPS / SSE
FastAPI backend (Vultr) ──► Web dashboard (activity + HUD mirror)
  · Guardrails ($250, approval required)
  · Event bus
  · Vault (Supabase)
        ⇅  REST
Standby Agent (Agentverse + Claude)  ◄── ASI:One (chat)
        ▲  ctx.send
Monitor Agent (Agentverse, reactive)
        │
Tools: Vault · Mock flights · ElevenLabs ──☎──► Simulated airline
```

**Principle:** the glasses are only display, microphone and tap. The brain lives on Fetch. The backend is the bridge.

### How G2 and Fetch connect

1. The judge taps to accept the alert (or says "Handle it") → the app sends the request to the backend.
2. The backend calls the **Standby Agent** (`@agent.on_rest_post`).
3. The agent reads the Vault, searches flights and picks the best option.
4. The agent emits events to the backend (`POST /events`) → the backend forwards them to the glasses and the dashboard.
5. The judge approves → the backend notifies the agent → the agent pays and calls via ElevenLabs.
6. The **Monitor Agent** watches flight status (`on_interval`) and notifies the orchestrator with native Fetch messages (`ctx.send`).

### Vault

- **Supabase Storage** (`vault` bucket): original files.
- **`vault_items` table**: data extracted by Claude.
- Uploaded from the **web dashboard** (laptop or phone browser). The glasses have no camera.

```sql
create table vault_items (
  id uuid primary key default gen_random_uuid(),
  user_id text,
  type text,        -- boarding_pass | receipt | call_transcript
  file_url text,
  data jsonb,       -- {"flight":"UA183","from":"LAX","to":"SFO","pnr":"ABC123"}
  created_at timestamptz default now()
);
```

---

## 3. Shared contract

### Events

| Event | Payload |
|---|---|
| `trip.requested` | `{origin, dest, deadline, max_price}` |
| `flight.booked` | `{flight, departure, arrival, price}` |
| `gate.changed` | `{flight, old_gate, new_gate}` |
| `boarding.soon` | `{flight, gate, minutes}` |
| `flight.cancelled` | `{flight, route}` |
| `task.started` | `{task_id}` |
| `option.found` | `{options: [...]}` |
| `approval.requested` | `{task_id, flight, arrival, price}` |
| `approval.granted` / `approval.rejected` | `{task_id}` |
| `payment.executed` | `{amount, method: "visa_token", reference}` |
| `call.started` | `{provider}` |
| `call.completed` | `{confirmation}` |
| `task.resolved` | `{new_flight, arrival, gate}` |
| `vault.updated` | `{type}` |

### Backend endpoints

```
POST /vault/upload      upload document, Claude extracts data
POST /voice             audio → text → agent
POST /approval          {task_id, approved}
GET  /events            SSE for glasses and dashboard
POST /events            agent publishes events
POST /trip/request      starts a booking (Act 1)
POST /simulate/gate     changes the gate (Act 2)
POST /simulate/boarding boarding alert (Act 2)
POST /simulate/cancel   marks the flight as cancelled (Act 3)
POST /demo/reset        resets everything to the initial state
GET  /flights/search    mock flights
```

### Standby Agent tools

- `get_booking(user_id)`
- `search_flights(origin, dest, deadline, max_price)`
- `request_approval(option)`
- `pay(amount, merchant)` — Visa (sandbox or simulated), only after approval
- `call_provider(script, context)`
- `save_to_vault(type, data)`

### Mock data

- Boarding pass: **UA183, LAX → SFO**.
- Alternatives: one too expensive (> $250), one that arrives late (> 10 PM), and the right one (**UA927, 8:40 PM, $215**).

### Rules enforced in code (not by the LLM)

- Max **$250** per purchase.
- **Never** pay without approval.
- The LLM **never** sees card data.

---

## 4. Demo (~2 min)

**The judge puts on the glasses before we start.**

**Act 1 — Book (~30 s)**
1. "You need to be in SF tomorrow before 10 PM, max $250." (voice or ASI:One)
2. HUD: `UA183 · 6:10 PM · $189 · Tap to buy`. **The judge taps.**
3. Dashboard: Visa payment ✓ · boarding pass saved to the Vault.

**Act 2 — Guide (~10 s)**
4. Now "at the airport": HUD `Gate changed: 52 → 61`.

**Act 3 — Resolve (~80 s)**
5. A teammate presses "simulate cancellation". HUD: `UA183 CANCELLED · Want me to fix it? Tap = yes`.
6. Dashboard: booking found in the Vault and 3 options; 2 discarded with the reason.
7. HUD: `UA927 · 8:40 PM · $215 · Tap to approve`. **The judge taps again.**
8. The agent calling the "airline" plays through the laptop. HUD: `☎ Calling United`.
9. HUD: `✓ Rebooked · UA927`. Vault updated. Closing line.

If Act 1 isn't ready, the demo starts directly at Act 3 with the boarding pass preloaded.

### HUD screens

- Max 2–3 lines, large text.
- The instruction is on screen (`Tap to approve`).
- Key screens wait for a tap; they don't disappear on their own.
- Tap = approve · double tap = reject.

### "Can the judge try it right now?"

- The judge only reads and taps. Voice is an extra we show ourselves.
- **Reset demo** button to repeat as many times as needed.
- If they reject → "Ok, here's another option".
- Beta installed on the phone (not local QR).
- Public backend + phone hotspot as backup.
- Everything charged + external battery.

### Answers for Even judges

- **Who and when?** A traveler at the airport, hands full and stressed.
- **Why G2?** You don't have to pull out your phone at the worst possible moment.
- **Can they try it now?** Yes, put them on.

### Fallbacks

- Glasses fail → even-dev simulator on screen.
- ElevenLabs or network fails → recording of a real call.
- Everything fails → video recorded at ~2 AM.

---

## 5. Task split

### Person 1 · Backend (Roberto)
- **First 2 h:** FastAPI on Vultr with `/events` (SSE), `/simulate/cancel` and `/demo/reset` using fixed data.
- **Then:** Vault on Supabase, guardrails, `/approval`, `/voice` (speech-to-text), mock flights, CORS.
- **Payment (Visa):** `pay()` with Visa sandbox if available; otherwise simulated with a reference. Confirm track and APIs at the Visa table.
- **Acts 1 and 2:** `/trip/request`, `/simulate/gate`, `/simulate/boarding` (after Act 3 works).

### Person 2 · Fetch agents
- **First 2 h:** uAgent registered on Agentverse with a REST endpoint that responds to the backend.
- **Then:** Standby Agent with Claude and tools, access via ASI:One, Monitor Agent (last).
- Confirm the judging rubric at the Fetch table.

### Person 3 · G2 glasses
- **First 2 h:** `asr` template running on the G2, showing text and detecting a tap.
- **3:00–4:00 PM:** Even workshop.
- **Then:** connect to `/events`, HUD screens, tap/double tap, package `.ehpk` and upload Beta.
- Until the backend is ready, simulate events locally.
- Hardware questions before **8 PM** (after that, Discord only).

### Person 4 · Voice + dashboard
- **First 2 h:** two ElevenLabs agents (the caller, which identifies itself as an AI, and the "airline") with a test call.
- **Then:** web dashboard (document upload, activity feed, HUD mirror, simulate/reset buttons).
- **At the end:** demo video and Devpost.

---

## 6. Timeline

| When | Goal |
|---|---|
| **Now** | README with the contract. Everyone gets their "hello world". |
| **3:00–4:00 PM** | Person 3 at the Even workshop. |
| **~4:30 PM** | Checkpoint: everyone shows their "hello world". |
| **~10 PM** | Each piece works on its own with mock data. |
| **~10 PM–2 AM** | Integration: full end-to-end flow. |
| **~2 AM** | Record backup video (Act 3). |
| **~2–5 AM** | Act 1 (booking + Visa) and Act 2 (alerts), reusing the engine. |
| **Overnight** | Monitor Agent, HUD polish, error cases. Sleep in shifts. |
| **Sun 8–10 AM** | Test with someone who has never used the glasses. |
| **Sun 10 AM** | **Code freeze.** Only Beta, Devpost and rehearsal. |
| **Sun 12:00 PM** | Submission. |

**Team rule:** if anyone is stuck for more than 30 minutes, say it out loud.

---

## 7. Submission checklist

### Even Hub
- [ ] App tested on a physical G2.
- [ ] `.ehpk` uploaded and available in Beta.
- [ ] Tested: phone locked 5 min, permissions denied, double tap to exit.
- [ ] App name ≤ 20 characters, no "Even" (`Standby` ✓).

### Devpost
- [ ] Description: what it does, what problem it solves, how it fits each track.
- [ ] Public repo with README.
- [ ] README section: how to install and run on G2 (required accounts and API keys).
- [ ] Even Hub app name.
- [ ] 2–3 min video showing the G2 experience (simulator or through-the-lens).
- [ ] Tracks selected: Even Realities, Fetch.ai, Visa (if applicable), ElevenLabs, Vultr.

### Judging day
- [ ] Team at the table.
- [ ] Demo running before the judge arrives.
- [ ] Return the G2 before leaving.

---

## 8. Out of scope

WhatsApp · JEV · extra verticals · Sentry · Devin. Mentioned in a single "same engine, other use cases" slide.
