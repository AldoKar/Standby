# G2 glasses app (owner: P3)

The glasses are display and gestures only. The engine sends every screen as a `hud.screen` event; the app renders its `lines` and posts gestures to `POST /input`.

## Wire it up

1. Start from Even's official template (minimal or asr) and get one line of text plus one gesture working on the G2.
2. Copy `src/handle-it-client.ts` into the app.
3. After `await waitForEvenAppBridge()`, call `connect(BACKEND_URL, screen => render(screen.lines))`. `render` updates your text container. Check the SDK README for the exact text-update call (the starter pack names `textContainerUpgrade`).
4. Enable `isEventCapture` on the container and handle `onEvenHubEvent`:
   - tap → `sendGesture(BACKEND_URL, 'press')`
   - long press → `sendGesture(BACKEND_URL, 'hold')`
   - swipe down → `sendGesture(BACKEND_URL, 'swipe_down')`
   - **double press: never.** On the root page it opens the system exit dialog.
5. Keep approval screens on a non-root page.
6. Add the engine's domain to the network whitelist in `app.json`. The engine must be HTTPS with a valid certificate. Until it's deployed, use your laptop's LAN IP, not localhost.

## Screens you will receive (demo order)

| screen_id | Lines | Gestures |
|---|---|---|
| `ready` | Ready / Tap to start | press = start |
| `cancelled` | UA183 cancelled / United: 7:05 AM tmrw / Tap = fix it | press = fix |
| `booking_offer` | Delta tonight 9:15 PM / $215 · lands 10:40 / Hold to book | hold = approve, swipe down = other |
| `booked` | Booked · pass saved | none |
| `calling` | Desk closes 11:00 PM / You land 10:40 / Calling guesthouse | none |
| `fee_request` | +$40 late check-in / Guesthouse asks / Hold = OK, Swipe = no | hold = approve, swipe down = reject |
| `resolved` | Room held / Door code 4417 (clears after 10 s) | press = dismiss |

You can drive the same flow from the dashboard (`GET /` on the engine) with the Press, Hold and Swipe buttons while the glasses app is still in progress.

## Checklist

- [ ] 4:30 PM: G2 shows text from the deployed engine, and a tap reaches the server
- [ ] 6:00 PM at the Even table: long press reaches the app; an idle display wakes when text updates; Even confirms in writing that booking/fee approvals are OK in the Beta
- [ ] 11:00 PM: Beta uploaded and passes the 5-minute phone-lock test
- [ ] iPhone, auto-lock off, phone hotspot for judging
