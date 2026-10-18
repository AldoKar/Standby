![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Standby

> **Your flight just got cancelled at 9 PM. Standby fixes the rest of your night.**

Standby is an AI travel agent on your **Even G2** glasses and in **ASI:One**. When your flight is cancelled it finds a way home tonight, asks you once for a spending limit, lets you pick a flight with a swipe, books it, **phones the guesthouse** to hold your room (real call, there's no API for that), checks what the clerk actually said, and claims back what your card's travel benefits cover. You approve every spend with a tap; code, not the model, decides what money can move.

Built at the **LA Hacks AI Hackathon 2026** (Oct 17–18).

**Tracks:** Fetch.ai (ASI:One Agent Challenge) · Even Realities · Visa · MLH ElevenLabs · MLH Vultr

---

## Contents

1. [The demo in one minute](#the-demo-in-one-minute)
2. [What's real and what's simulated](#whats-real-and-whats-simulated)
3. [Fetch.ai agents](#fetchai-agents)
4. [Architecture](#architecture)
5. [Run it locally](#run-it-locally)
6. [Install and run on G2](#install-and-run-on-g2)
7. [Configuration](#configuration)
8. [Tests](#tests)
9. [Trust and safety](#trust-and-safety)
10. [Repository](#repository)
11. [Team](#team)

---

## The demo in one minute

| Step | On the glasses | What the agent does |
|---|---|---|
| Before the trip | `Ready / Tap = start, Hold = ask` | Your flight is a real LAX→SFO flight from FlightAware. Hold and ask anything, in any language: "Is my flight on time?" |
| Cancelled | `UA183 cancelled / Fix it for up to $300? / Tap = yes, Hold = budget, Swipe = no` | Claude checks the flight, searches tonight's flights, picks one and proposes a spending limit from the real fares, with its reasoning |
| Choose | `→ Delta 9:15 PM $215` · `Alaska 9:45 PM $239` · `WN2210 10:00 PM $229` | Up to three flights that fit the limit. Swipe to move, tap twice to book. Policy re-checks the spend; the payment is signed |
| Call | `Desk closes 11:00 PM / You land 10:40 / Calling guesthouse` | Claude sees you'll arrive after the desk closes and decides to call. An ElevenLabs voice agent phones the guesthouse |
| Mid-call fee | `+$40 late check-in / Hold = OK, Swipe = no` | The clerk asks for a fee; you approve it on the glasses while the call is live. Every fee is asked, whatever the amount |
| Outcome | `Room held / Door code 4417` | Claude reads the transcript; the door code is shown only if the clerk really said it |
| Money back | `Trip claim ready / $66 back expected / Tap = submit` | Claude drafts a travel-benefit claim from your receipts ($215 − $189 airline refund + $40 fee); code checks every dollar. Net cost of the cancellation: $0 |

The same flow runs from a chat in [ASI:One](https://asi1.ai), with interactive cards for the options, the review and the result.

## What's real and what's simulated

| Real | Simulated (and labeled so) |
|---|---|
| Claude (Opus 5.5) planning with tools: checks the flight, searches, chooses, proposes the limit, decides whether to call, drafts the claim | The cancellation itself (we can't cancel a real flight on stage) |
| Live flight status and the traveler's real flight (FlightAware AeroAPI) | The alternative flights in the demo (`FLIGHTS_MODE=mock`) |
| Flight search and test-mode orders with a PNR (Duffel, `FLIGHTS_MODE=duffel`) | Money: payments are signed and checked, but no funds move |
| A real outbound phone call (ElevenLabs + Twilio), verified against its transcript | Travel-benefit terms and claim submission (no public Visa claims API; see [`docs/TRAVEL-CLAIMS.md`](docs/TRAVEL-CLAIMS.md)) |
| Agent-to-agent hiring over the Fetch.ai Payment Protocol | FET settlement between agents (the handshake is real; the wallets are unfunded) |
| Ed25519 request signatures modeled on Visa's Trusted Agent Protocol, with a public key directory | The merchant that verifies them (the engine plays it) |

## Fetch.ai agents

| Agent | Name | Address | Job |
|---|---|---|---|
| Orchestrator | `standby` | `agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf` | ASI:One front door: plans within the traveler's mandate with Claude, calls the engine, shows interactive cards |
| Caller | `standby-caller` | `agent1q2480yjzfu7jv4sk7x9v2s0v7zf89mj9czpqs3sqtaypt5kyd4xkg7yge07` | Places disclosed AI phone calls to businesses with no API; hired and paid $1.99 per call over the Agent Payment Protocol |

- **Chat Protocol:** `AgentChatProtocol 0.3.0`. **Payment Protocol:** `AgentPaymentProtocol 0.1.0`.
- **Try it in ASI:One:** shared chat with the whole flow: https://asi1.ai/shared-chat/908014af-42c3-4614-8370-98459629cda1
- Details, versions and how to run the agents: [`agents/README.md`](agents/README.md).

## Architecture

```
 Even G2 glasses ──┐                         ┌── ASI:One chat
 (HUD, tap, mic)   │                         │
 g2-app (Even Hub) │                         │  standby (orchestrator, Agentverse)
                   │                         │      │ hires, pays $1.99 (Payment Protocol)
                   ▼                         ▼      ▼
              ┌───────────── engine (FastAPI on Vultr, HTTPS) ─────────────┐
              │ Claude agent loop (plan · arrival · claim · ask)           │
              │ policy.py: mandate rules: budget, merchants, expiry        │
              │ claims.py: benefit rules  ·  tap.py: signed payments       │
              │ SSE /events → glasses + dashboard  ·  Vault  ·  ledger     │
              └──┬───────────┬────────────┬────────────┬──────────────────┘
                 ▼           ▼            ▼            ▼
            FlightAware   Duffel     ElevenLabs +   Claude
            (status)      (flights)  Twilio (call)  (verifies the call)
```

- The **engine** owns the flow, the money rules and every word on the glasses (`hud.screen` events).
- The **glasses** only render lines and send gestures (`POST /input`) and voice (`POST /voice`, `POST /ask`).
- **ASI:One** drives the same engine through the orchestrator agent.
- The interface between all parts is in [`contract/`](contract/): [`events.md`](contract/events.md), [`api.md`](contract/api.md), [`mock-data.json`](contract/mock-data.json).

## Run it locally

Requirements: Python 3.11+, Node 20+.

**1. Engine** (works with no keys at all: everything falls back to mock data)

```bash
cd engine
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # optional: add keys, see Configuration
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 for the dashboard, or drive the flow with curl:

```bash
curl -X POST localhost:8000/input -H "Content-Type: application/json" -d '{"gesture":"press"}'
```

`press` starts the flow and accepts the limit, `swipe_down` moves through the flights, `hold` books and approves the fee. Reset with `POST /demo/reset`.

**2. Glasses app** (browser mirror and simulator)

```bash
cd g2-app
npm install
npm run dev      # http://localhost:5173 (keys: Space = tap, H = hold, ↓ = swipe)
npm run sim      # optional: the Even Hub simulator
```

**3. Agents** (ASI:One): see [`agents/README.md`](agents/README.md). They need `ENGINE_URL` and an Anthropic key.

The deployed engine runs on Vultr behind Caddy (HTTPS, systemd): [`engine/DEPLOY.md`](engine/DEPLOY.md).

## Install and run on G2

How to install Standby on the G2, what it does on the glasses and how it works: [`g2-app/README.md`](g2-app/README.md).
No API keys are needed to test it.

## Configuration

All keys are optional; without them the engine runs the full flow on mock data. **Testers using the hosted engine need none of these.** Copy [`engine/.env.example`](engine/.env.example) to `engine/.env` (never commit it).

| Variable | What it turns on |
|---|---|
| `ANTHROPIC_API_KEY` | Claude: call verification, free questions (`POST /ask`), and with `AGENT_MODE=claude` the agent loop |
| `AGENT_MODE=claude` | Claude plans, proposes the limit, decides whether to call and drafts the claim (`off` = scripted flow) |
| `AEROAPI_KEY`, `LIVE_FLIGHT=auto` | Live flight status (FlightAware) and the traveler's real flight before Start |
| `FLIGHTS_MODE=duffel`, `DUFFEL_TOKEN` | Live flight search and test-mode orders (`mock` = demo fares) |
| `CALL_MODE=elevenlabs`, `ELEVENLABS_*`, `CALL_TO_NUMBER` | A real outbound phone call (`mock` = simulated clerk) |
| `OPENROUTER_API_KEY` | Voice commands on the glasses (speech to text and intent) |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY` | Picking a flight by voice ("the Alaska one"); local Ollama, or Ollama Cloud with `OLLAMA_URL=https://ollama.com` and a key. Without it a keyword match is used |
| `PUBLIC_URL`, `TAP_PRIVATE_KEY` | The signing key directory URL and a stable signing key |

## Tests

```bash
cd engine && python test_engine.py      # 23 end-to-end cases, no network, no cost
cd engine && python -m app.claims       # claim rules self-check
cd agents && python test_agents.py      # the orchestrator against a running engine
cd g2-app && npm run build              # type-check and build the glasses app
```

The engine suite stubs Claude, Duffel, FlightAware and ElevenLabs, and covers the SPEC's hostile cases: over-budget fees, wrong merchants, retracted door codes, calls that never connect, stale gestures, replayed signatures and over-claims. Results are served at `GET /tests` for the dashboard. A clerk asking for a card number is handled by the voice agent's prompt ([`voice/README.md`](voice/README.md)): it never gives, asks for or repeats card numbers.

## Trust and safety

- **Code decides money, never the model.** Every spend goes through `engine/app/policy.py` (budget, merchant categories, expiry), which can only deny or ask: nothing is paid without the traveler's OK. Claude can propose a limit or a claim; code rounds, caps and checks it, and refuses anything else.
- **Consent at the moment it matters.** One tap for the limit, one for every flight and every fee, whatever the amount. Voice can never approve a spend: it asks for a tap.
- **Signed payments.** Each merchant request is signed (RFC 9421, Ed25519, `agent-payer-auth`), modeled on Visa's Trusted Agent Protocol; the public key is at `/.well-known/http-message-signatures-directory`. Tampering and replays are refused.
- **Verified outcomes.** A door code reaches the glasses only if Claude marks the call verified and the code literally appears in the transcript.
- **Disclosed calls.** The voice agent says it's an AI assistant, and never reads out card details.
- **Fallbacks everywhere.** If Claude, Duffel, FlightAware or the call fails, the flow continues on the scripted path and says so.

## Repository

```
engine/      FastAPI engine: flow, Claude agent, policy, claims, signed payments, SSE (P1)
agents/      Fetch.ai uAgents: orchestrator and caller, ASI:One cards, Payment Protocol (P2)
g2-app/      Even G2 app: Vite + React + Even Hub SDK, voice, browser mirror (P3)
voice/       ElevenLabs voice agent setup and tools (P4)
dashboard/   Judge dashboard served by the engine (P4)
contract/    The shared interface: events, API, mock data
docs/        SPEC.md (the product), TRAVEL-CLAIMS.md (claims research)
```

`backend/`, `contracts/` and `frontend/` are from an earlier plan and aren't used.

## Team

| Role | Owner |
|---|---|
| Engine: flow, Claude agent, policy, payments, deploy | Roberto Ochoa Cuevas |
| Fetch.ai agents and ASI:One | Heechan Yang |
| G2 glasses app | Aldo Karim |
| Voice agent (ElevenLabs) and dashboard | Feruz Karimov |
