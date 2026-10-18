# G2 glasses app: Standby (owner: P3)

Vite + React + Even Hub SDK. The engine writes every screen (`hud.screen`); this app renders it on the G2 and on a
browser mirror, and posts gestures to `POST /input`. Contract: `contract/events.md`, `contract/api.md`.

## Run

```bash
# terminal 1: engine (see GETTING-STARTED.md)
cd engine && uvicorn app.main:app --host 0.0.0.0 --port 8000

# terminal 2: this app
cd g2-app && npm install && npm run dev        # http://localhost:5173

# terminal 3: simulator
cd g2-app && npm run sim
```

Engine URL, in order: `?api=https://host`, `VITE_ENGINE_URL`, otherwise the page's own host on port 8000
(so QR sideload on the laptop's LAN IP finds the engine on the same IP).

Real glasses (QR sideload), from the repo root (the CLI's peer dep conflicts with TypeScript 6 inside g2-app):

```bash
npx -y @evenrealities/evenhub-cli@0.1.14 qr --url "http://<LAN-IP>:5173"
```

## How it renders (design option B)

The engine's `lines` are shown verbatim. The app only decides the look (`src/hud/screens.ts`):

- Icon, alert border and a small status header per `screen_id` (e.g. `calling` → "STANDBY IS CALLING", phone icon,
  voice-wave animation).
- The gesture line ("Hold = OK, Swipe = no", "Hold to book", "Tap = fix it") becomes one native hint line at the
  bottom, left-aligned like Even's own apps: "Tap = book  ·  Swipe ↓ = other". Labels come from that line, or from
  `gestures` values for gestures the line doesn't mention ("other"). No fake buttons, so nothing to centre.
- `clear_after_s` blanks the lens; an empty `lines` is a blank lens.
- Never "pay", "card" or "Visa" in the app-owned header.

## Gestures

| Temple | Sent | Notes |
|---|---|---|
| Tap | `press` | On approval screens (engine offers `hold`, not `press`): opens a local "Tap again to confirm" screen |
| Tap again (on confirm) | `hold` | for the original screen; the confirm screen times out back to the offer after 6 s |
| Long press | `hold` | still approves directly |
| Swipe down | `swipe_down` | on the confirm screen: back, nothing sent. Ignored for 900 ms after a new screen (stray scroll events on rebuild) |
| Double press | nothing | `DOUBLE_TAP_EXITS = false` in `src/glasses/bridge.ts`. ⚠ Even review expects double press to exit; flip it if they ask |

Only gestures listed in the current screen's `gestures` are sent, always with its `screen_id`, one at a time.
Tap-then-confirm is the SPEC's long-press fallback, done on the glasses so the engine contract is unchanged.

Presenter keys on the page: Space = tap, H = hold, ↓ = swipe down.

## Dev tools

- Footer → Developer tools (or `?dev`): on-device log, screen previews, glyph probe.
- `?shot=<screen_id>` (DEV only) previews one engine screen offline, without connecting to the engine.

## Checklist

- [x] Renders `hud.screen` from the engine and sends press / hold / swipe_down (simulator, local engine)
- [x] Full demo flow in the simulator against the mock engine: ledger $255 spent, $45 left, net $66
- [ ] 4:30 PM: G2 shows text from the deployed engine over HTTPS, and a tap reaches the server
- [ ] Swipe down on real G2 arrives as SCROLL_BOTTOM_EVENT (verify)
- [ ] 6:00 PM at the Even table: long press works, idle display wakes on text update, root vs non-root pages for
      approvals, written OK for booking/fee approvals in the Beta
- [ ] `app.json`: package_id, name "Standby", network whitelist with the engine's HTTPS origin
- [ ] 11:00 PM: Beta uploaded; passes the 5-minute phone-lock test
- [ ] iPhone, auto-lock off, phone hotspot for judging

## Notes for other owners

- P1: `/input` ignores `screen_id`; rejecting gestures for a stale `screen_id` would protect money screens.
- P1: "Room not held" reuses `screen_id: resolved`; a separate id would let the glasses style it as a failure.
- P1: `contract/api.md` says policy lives in `backend/app/policy.py`; it's `engine/app/policy.py`.
- P1/everyone: SPEC still says "Handle It"; the app uses "Standby".
