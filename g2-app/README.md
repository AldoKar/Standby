# Standby for Even G2

Standby is a travel assistant on your **Even Realities G2** glasses. When your flight is cancelled, it shows you
tonight's options on the lens, books the one you pick, phones your hotel so they hold your room, and gets your money
back, asking you on the glasses before it spends a single dollar.

## Install it on your G2

### What you need

| Item | Needed? | Notes |
|---|---|---|
| **Even G2 glasses** | Yes | Charged and paired with your phone |
| **Phone with the Even Realities app** | Yes | iPhone or Android, app version **2.2.10 or newer** |
| **Even Realities account** | Yes | Sign in to the Even app and pair the G2 there |
| **Access to the Standby beta** | Yes, for option A | Even Hub app **Standby** (`com.standby.g2`), Beta **0.1.1**. Ask the team to add your Even account as a tester |
| **API keys** | **No** | The beta talks to our hosted engine (`https://149.28.76.19.sslip.io`), which already has them |
| Internet on the phone | Yes | Wi-Fi or cellular |

### Option A: install the beta from Even Hub (recommended)

1. Open the **Even Realities** app, sign in, and check that the G2 shows as connected.
2. Install **Standby** (Beta 0.1.1) from Even Hub.
3. Open **Standby** on the glasses. You'll see the Standby logo with *Connecting…*, then
   **"Ask Standby about your travel"** with *Tap = start · Hold = ask*.

### Option B: open it with a QR (no install, no keys)

Runs everything on a laptop (Python 3.11+, Node 20+) on the **same Wi-Fi** as your phone. With no keys it uses demo
data and a simulated phone call.

```bash
# terminal 1: engine (from the repo root)
cd engine
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# terminal 2: glasses app
cd g2-app
npm install
npm run dev
```

1. Open http://localhost:5173 and press **Link glasses** (top right).
2. Scan the QR with the **Even Realities** app. Standby opens on your G2.

## What it does

| Screen on the lens | What's happening | What you do |
|---|---|---|
| **Home**: Standby logo, *Ask Standby about your travel* | Waiting, watching your trip | **Tap** to start the demo. **Hold** and ask anything about your trip, in any language |
| **UA183 cancelled · Fix it for up to $300?** | Your flight was cancelled; Standby found tonight's flights and proposes a budget from their prices | **Tap** = yes. **Hold** = set another budget: say an amount ("450"), then **tap** to confirm or **swipe** to roll back. **Swipe down** = no |
| **Pick your flight** | Up to three flights that fit your budget | **Swipe** to move, **tap** a flight, then **tap again** on *Confirm with a tap* to book it. Or say "the Alaska one" |
| **Calling guesthouse** | You'll land after the front desk closes, so an AI voice agent phones your hotel to hold the room | Nothing. **Hold** hides the call to a small icon (or say "hide it") |
| **+$40 late check-in** | The hotel asked for a fee during the call; the call waits for your answer | **Tap**, then **tap again** to approve. **Swipe down** to decline |
| **Room held · Door code 4417** | The call is done; the door code is shown only if the clerk really said it | **Tap = next** |
| **Trip claim ready · $66 back expected** | Standby worked out what your card's travel benefits pay back | **Tap** submits the claim, **swipe down** keeps it for later |

## How it works

- **The glasses are a screen, a mic and a touchpad.** Standby runs inside the Even app on your phone and draws on the
  G2's 576×288 display. Every decision happens on the Standby engine; the glasses show its screens and send back your
  gestures and voice.
- **You approve every payment.** The flight, every hotel fee, whatever the amount: nothing is ever paid without your
  OK on the glasses. Approvals always need a **tap**; voice can never approve a payment (saying "yes" only opens
  *Confirm with a tap*).
- **Tap and talk.** Everything except payments also works by voice. The tag in the top-right corner of every screen
  tells you before you speak: *○ Voice on* (you can talk), *● Listening* (it's hearing you), *● Heard you*,
  *? Say again*, or *Tap only*. The start screen is tap only, so nearby talk can't start anything.
- **The phone call is real.** An ElevenLabs voice agent calls the hotel, says it's an AI, and checks with you on the
  glasses before agreeing to any fee.

### Gestures

| On the temple | Does |
|---|---|
| **Tap** | Start, yes, pick, next. On a payment it opens *Confirm with a tap*; tap again to pay |
| **Long press (hold)** | Ask a question (home screen), change the budget (cancelled screen), hide or show the call |
| **Swipe down** | No, next flight, roll back, back |
| **Double press** | Exit Standby |

### Voice commands

| Screen | Say |
|---|---|
| Cancelled | "yes", "no", "make it 450", "change the budget" |
| Pick your flight | "book it", "the Alaska one", "the cheapest", "the ten o'clock" (then tap to confirm) |
| Hotel fee | "yes" (then tap to confirm), "no" |
| Calling | "hide it", "show the call" |
| Room held, claim, answers | "OK", "got it", "done" |
| Home | Hold, then ask anything: "Is my flight on time?" |

## If something looks wrong

| You see | Do this |
|---|---|
| *Offline · Can't reach Standby* | Check the phone's internet. Engine status: https://149.28.76.19.sslip.io/state |
| *Voice off* in the corner | The mic sent no audio: close and reopen Standby. Taps keep working |
| Someone else's flow on the lens | Another tester is on the shared engine: open https://149.28.76.19.sslip.io and press **Reset** |
| Blank lens or a stuck screen | Close Standby completely in the Even app and open it again |

To start over at any time: open the engine page (https://149.28.76.19.sslip.io, or http://localhost:8000 for
option B) and press **Reset**.

## Build the beta yourself

```bash
cd g2-app
npm install
npm run pack      # builds, checks every URL against app.json's whitelist, writes standby-beta.ehpk
```

Upload `standby-beta.ehpk` to Even Hub as a beta (bump `version` in `app.json` first). The hosted engine address is
set in `vite.config.ts` (`PROD_ENGINE_URL`) and must match the network whitelist in `app.json`.
