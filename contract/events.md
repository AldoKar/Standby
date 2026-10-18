# Events

Every event the engine sends on `GET /events` (Server-Sent Events) uses one envelope. Events arrive as plain `message` events, so `EventSource.onmessage` receives all of them; switch on `type`.

```json
{"type": "hud.screen", "ts": "2026-10-18T05:12:03.120Z", "task_id": "task-3f9a1c2e", "data": {}}
```

On connect, the engine first sends `state.snapshot`, then the current `hud.screen`, so a client that reconnects redraws immediately. A comment line (`: heartbeat`) arrives every 15 seconds.

| Event | When | `data` |
|---|---|---|
| `state.snapshot` | First message after connecting | Full state, same as `GET /state` |
| `hud.screen` | The glasses should show something new | `screen_id`, `lines` (at most 3), `gestures`, `clear_after_s` |
| `flight.cancelled` | The flow starts | `flight`, `route`, `airline_offer`, `source` |
| `options.ranked` | The policy engine has filtered the options | `options[]`, each with `verdict` (pick, ok, rejected) and `reason`; `source` (`duffel` = live fares, `mock`), `error` (why Duffel fell back to mock, else null), `chosen_by` (`agent` = Claude chose the pick, with `agent_reason` on it; `policy` = the scripted rule). `day` is `today` or `tomorrow`/`later`. Live options also carry `offer_id`, `stops`, `currency` |
| `mandate.checked` | Any spend is checked | `kind`, `amount`, `remaining`, `result` (allow, ask, deny), `reason` |
| `approval.requested` | A spend needs the wearer's OK | `approval_id`, `kind` (booking, fee), `amount`, `merchant`, `reason` |
| `approval.granted` / `approval.rejected` | The wearer or ASI:One answered | `approval_id`, `kind`, `via` (glasses, asi1, api) |
| `payment.executed` | A spend went through (simulated) | `amount`, `merchant`, `mcc`, `token_id`, `reference`, `signature` (`keyid`, `tag`, `verified`: the TAP-style signed request the merchant checked) |
| `agent.step` | Claude (AGENT_MODE=claude) did something | `phase` (`plan`: check flight, search, choose; `arrival`: check arrival, maybe call), `kind` (`tool` or `thought`), `tool`, `input`, `result`, `error`; or `text` for a thought |
| `agent.done` | Claude finished a phase | `phase`, `text` (one sentence for the traveler: what it did and why) |
| `agent.failed` | Claude errored or timed out; the scripted flow takes over | `phase`, `error` |
| `flight.booked` | The booking went through after the wearer approved it | `airline`, `flight`, `source` (`duffel`, `mock`), `order_id`, `pnr` (null for mock fares), `error`? (the Duffel order failed) |
| `offer.declined` | The airline's own rebooking is turned down | `airline`, `flight`, `refund_usd`, `status` |
| `vault.updated` | Something was saved to the Vault | `type` (boarding_pass, call_transcript), `id`, `title`. The item itself is in `GET /vault` |
| `cutoff.detected` | The agent spots a downstream problem | `place`, `closes_at`, `arrival`, `eta` |
| `call.started` | The phone call starts | `to`, `purpose`, `mode` (mock, elevenlabs) |
| `call.completed` | The call ended | `outcome` (`held`, `fee_usd`, `door_code`, `contact`), `transcript_url`, `verified` |
| `task.resolved` | The whole fix is done | `flight`, `lodging` (`held`, `door_code`) |
| `voice.heard` | A voice command was transcribed and classified (`POST /voice`) | `screen_id`, `transcript`, `intent` (or `unknown`), `confidence`, `via` (keywords, model, none) |
| `demo.reset` | Reset was pressed | `{}` |

## `hud.screen` in detail

```json
{
  "screen_id": "booking_offer",
  "lines": ["Delta tonight 9:15 PM", "$215 · lands 10:40", "Hold to book"],
  "gestures": {"hold": "approve", "swipe_down": "other"},
  "clear_after_s": null
}
```

- The engine writes all screen copy. The glasses only render `lines` and send gestures.
- `gestures` lists the gestures that do something on this screen. Send them to `POST /input` together with this `screen_id`; a gesture for a screen that has since changed is ignored.
- `clear_after_s`: blank the screen after this many seconds; `null` keeps it.
- An empty `lines` array means a blank screen.

The demo flow's screen ids, in order: `ready`, `searching` ("UA183 cancelled / Finding flights...", gestures ignored), `cancelled`, `booking_offer`, `booked` ("Booked · PNR X7K2QZ / Pass saved" for a live Duffel order, else "Booked · pass saved"), `calling`, `fee_request`, `resolved`. Other screens that can appear: `only_option` (swipe down on the booking offer), `no_option` (no flight fits: "No flight tonight / fits your budget"), `denied` (a spend broke the mandate), `call_resumed` (the wearer answered the fee and the call goes on: "+$40 OK / Finishing the call" or "Fee declined / Finishing the call"; replaced by the outcome when the call ends), `resolved` can also read "All set / No call needed" (Claude found the traveler arrives before the desk closes and didn't call), `call_failed` (the call never connected: "Call didn't connect / Details on your phone"), `not_held` (the call ended without holding the room: "Room not held / Details on your phone"; the stage is still `resolved`) and `idle` (blank, shown for a moment when a finished task is dismissed, before `ready`).
