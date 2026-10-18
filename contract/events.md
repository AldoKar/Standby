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
| `options.ranked` | The policy engine has filtered the options | `options[]`, each with `verdict` (pick, ok, rejected) and `reason` |
| `mandate.checked` | Any spend is checked | `kind`, `amount`, `remaining`, `result` (allow, ask, deny), `reason` |
| `approval.requested` | A spend needs the wearer's OK | `approval_id`, `kind` (booking, fee), `amount`, `merchant`, `reason` |
| `approval.granted` / `approval.rejected` | The wearer or ASI:One answered | `approval_id`, `kind`, `via` (glasses, asi1, api) |
| `payment.executed` | A spend went through (simulated) | `amount`, `merchant`, `mcc`, `token_id`, `reference` |
| `offer.declined` | The airline's own rebooking is turned down | `airline`, `flight`, `refund_usd`, `status` |
| `vault.updated` | Something was saved to the Vault | `type` (boarding_pass, call_transcript) |
| `cutoff.detected` | The agent spots a downstream problem | `place`, `closes_at`, `arrival`, `eta` |
| `call.started` | The phone call starts | `to`, `purpose`, `mode` (mock, elevenlabs) |
| `call.completed` | The call ended | `outcome` (`held`, `fee_usd`, `door_code`, `contact`), `transcript_url`, `verified` |
| `task.resolved` | The whole fix is done | `flight`, `lodging` (`held`, `door_code`) |
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
- `gestures` lists the gestures that do something on this screen. Send them to `POST /input`.
- `clear_after_s`: blank the screen after this many seconds; `null` keeps it.
- An empty `lines` array means a blank screen.

The demo flow's screen ids, in order: `ready`, `cancelled`, `booking_offer`, `booked`, `calling`, `fee_request`, `resolved`. Other screens that can appear: `only_option` (swipe down on the booking offer), `denied` (a spend broke the mandate) and `call_failed` (the call never connected: "Call didn't connect / Details on your phone").
