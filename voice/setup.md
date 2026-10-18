# Voice agent setup: ElevenLabs + Twilio (owner: P4)

Goal: after the wearer books Delta, the engine phones the demo table, the agent asks for the room, pauses on the $40 fee until the wearer holds on the glasses, and after the call the engine checks what was agreed against the transcript. About 30 minutes to set up.

Checked against the ElevenLabs API reference on Oct 17, 2026. UI labels move around; if one doesn't match, look for the nearest equivalent.

## 0. Before you start

You need:

- An ElevenLabs account and an API key with access to ElevenLabs Agents (Profile → API keys; if the key has scoped permissions, allow Agents).
- A Twilio account, **upgraded** ($20). A trial account plays a trial message and can only call verified numbers.
- The engine on a public HTTPS URL. On Vultr that's P1's host. For testing on a laptop, use a tunnel:
  ```bash
  cloudflared tunnel --url http://localhost:8000
  ```
  It prints `https://<random>.trycloudflare.com`. That host is `<ENGINE_HOST>` below; it changes every time you restart the tunnel, so update the tool URLs.
- The phone on the demo table, in E.164 (`+13105550123`).

## 1. Twilio number

1. Twilio Console → Phone Numbers → Buy a number. A US local number with Voice.
2. Note the **Account SID** and **Auth Token** (Console home). A restricted API key works too: its SID starts with `SK`, and you use its secret as the token.

## 2. Create the agent

ElevenLabs → Agents → Create agent → Blank. Name it `Handle It caller`.

| Setting | Value |
|---|---|
| First message | Copy from [README.md, First message](README.md#first-message), with the `{{...}}` variables as they are |
| System prompt | Copy the block from [README.md, System prompt](README.md#system-prompt) |
| LLM | The fastest model listed (a Claude Haiku model if offered). Latency matters more than depth here |
| Voice | A clear, calm English voice. Test it on a phone speaker, not headphones |
| Language | English |
| Max conversation duration | 120 seconds (Advanced) |
| System tools | Turn on **End call**, so the agent can hang up |

**Dynamic variables.** The first message uses `guest_name`, `confirmation` and `eta`; the engine also sends `task_id`. When you save, ElevenLabs lists them under dynamic variables. Give each a placeholder so test calls from the dashboard work:

| Variable | Placeholder | What the engine sends |
|---|---|---|
| `guest_name` | `Alex Rivera` | `traveler.name` from `contract/mock-data.json` |
| `confirmation` | `48213` | `lodging.confirmation` |
| `eta` | `11:30 PM` | Delta lands 10:40 PM + 50 min to the guesthouse |
| `task_id` | `task-test` | The engine's current task |

Names are case-sensitive and must match exactly, or the agent reads `{{eta}}` out loud.

**Data collection** (Analysis tab, required): the engine reads these four fields from the post-call webhook (step 5), so the names must match exactly.

| Identifier | Type | Description |
|---|---|---|
| `held` | boolean | True only if the clerk agreed to hold the room tonight |
| `door_code` | string | The door or key-box code exactly as the clerk said it; empty if none or taken back |
| `contact` | string | First name of the person the guest should ask for |
| `fee_usd` | number | Extra fee agreed on the call in US dollars, 0 if none |

## 3. The two tools

Both are webhook (server) tools. The exact config is in [`tools.json`](tools.json); each entry is an ElevenLabs `tool_config`. Replace `<ENGINE_HOST>` with your host.

Agent → Tools → Add tool → Webhook, then fill in:

### `request_approval`

| Field | Value |
|---|---|
| Name | `request_approval` |
| Description | Copy from `tools.json` |
| Method, URL | `POST https://<ENGINE_HOST>/call/approval` |
| Body parameters | `amount` (number, required, "Amount in US dollars"); `reason` (string, required, "Short reason, e.g. late check-in") |
| Response timeout | 10 s |
| Pre-tool speech | Force, so the clerk hears "One moment, let me check with him" before the glasses light up |

### `check_approval`

| Field | Value |
|---|---|
| Name | `check_approval` |
| Method, URL | `GET https://<ENGINE_HOST>/call/approval/{approval_id}` |
| Path parameter | `approval_id` (string, LLM prompt, "The approval_id returned by request_approval") |
| Query parameter | `wait_s`, integer, constant value `8` |
| Response timeout | 15 s |
| Tool call sound | Typing, so the line isn't silent while it waits |

`wait_s=8` makes each check wait up to 8 seconds for the wearer, so 4 checks cover about 30 seconds. The engine supports it from `p1-engine` on; on an older build `wait_s` is ignored and each check returns at once, which gives the wearer only about 10 seconds.

**By API instead of the UI** (one call per tool, then attach the returned `id`s on the agent's Tools tab):

```bash
python3 -c 'import json,sys; [print(json.dumps({"tool_config": t})) for t in json.load(open("voice/tools.json"))["tools"]]' \
  | sed "s/<ENGINE_HOST>/$ENGINE_HOST/g" \
  | while read -r body; do
      curl -s https://api.elevenlabs.io/v1/convai/tools -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" -d "$body"; echo
    done
```

## 4. Import the Twilio number

1. ElevenLabs → Agents → **Phone Numbers** → Import number → From Twilio.
2. **Label** `Handle It demo`, **Phone Number** your Twilio number, **Twilio SID** and **Twilio Token** from step 1.
3. Assign the `Handle It caller` agent to the number, so a callback from the guesthouse reaches the same agent.

ElevenLabs configures Twilio itself; you don't touch webhooks or TwiML.

## 5. Post-call webhook

This is how the engine learns the call ended. When the agent hangs up, ElevenLabs sends the transcript and the data collection fields to the engine; Claude checks them against the transcript, and the glasses show the door code only if it's verified (`engine/app/verify.py`, P1's code).

1. ElevenLabs → Agents → Settings → Post-call webhook (workspace settings): create a webhook with URL `https://<ENGINE_HOST>/call/webhook` and turn on transcription webhooks.
2. Copy the webhook secret it shows into `ELEVENLABS_WEBHOOK_SECRET` in `engine/.env` (step 7). Without it, or with the wrong one, the engine answers 401 and the call never finishes.
3. Set `ANTHROPIC_API_KEY` in `engine/.env` (engine builds before `p1-engine` used `GEMINI_API_KEY`). Without it nothing is verified, and the glasses show "Room held / Door code on phone" instead of the code.

The engine ignores webhooks whose `task_id` isn't the current task, so test calls from the ElevenLabs page (placeholder `task-test`) and calls from before a Reset don't touch the demo.

## 6. First test call, from ElevenLabs

Phone Numbers → your number → **Outbound call** → pick `Handle It caller` → your phone → Send Test Call.

Pass when: the phone rings within a few seconds, the first sentence says it's an AI and the call is recorded, and the placeholders are read as values (`Alex Rivera`, `48213`). This is the **7:00 PM milestone**.

The tools will fail on this call if the engine has no pending approval; that's expected.

## 7. Let the engine place the call

Get the two IDs:

- **Agent ID:** the agent's settings page (also in its URL), starts with `agent_`.
- **Phone number ID:**
  ```bash
  curl -s https://api.elevenlabs.io/v1/convai/phone-numbers -H "xi-api-key: $ELEVENLABS_API_KEY" | python3 -m json.tool
  ```
  Copy `phone_number_id` for your number.

In `engine/.env` (never commit it):

```
CALL_MODE=elevenlabs
ELEVENLABS_API_KEY=...
ELEVENLABS_AGENT_ID=agent_...
ELEVENLABS_PHONE_NUMBER_ID=...
CALL_TO_NUMBER=+1...
ELEVENLABS_WEBHOOK_SECRET=...
ANTHROPIC_API_KEY=...
```

On the Vultr box, systemd loads `/opt/handle-it/engine/.env` (see [`engine/DEPLOY.md`](../engine/DEPLOY.md)); after editing it, run `systemctl restart handle-it`. On a laptop, the engine loads `engine/.env` by itself (from `p1-engine` on); on an older build, load it first:

```bash
cd engine && set -a && source .env && set +a && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The dashboard header shows `call: elevenlabs` when the mode took.

What the engine sends (`engine/app/call.py`), checked against `POST /v1/convai/twilio/outbound-call`:

```json
{
  "agent_id": "agent_...",
  "agent_phone_number_id": "...",
  "to_number": "+1...",
  "conversation_initiation_client_data": {
    "dynamic_variables": {"guest_name": "Alex Rivera", "confirmation": "48213", "eta": "11:30 PM", "task_id": "task-..."}
  }
}
```

Header `xi-api-key`. The response is `{success, message, conversation_id, callSid}`. The request is right, and from `p1-engine` on, a `success: false` reply shows as a failed call.

## 8. Full run with a mid-call approval

1. Dashboard → Reset → Simulate cancellation → Press → Press → Hold (books Delta).
2. "Calling guesthouse" appears and the phone rings. Answer on speaker.
3. The clerk follows the card below. When the agent says "One moment, let me check with him", the glasses (and the dashboard HUD) show `+$40 late check-in`.
4. Wait 5 to 20 seconds, then Hold. The agent agrees to the fee, gets the door code, repeats it back and hangs up.
5. A few seconds after the hang-up, the webhook arrives and Claude checks the transcript. The glasses show `Room held / Door code 4417`; the dashboard call panel shows the outcome, the check's summary and any issues, and the ledger shows Delta $215 + fee $40.

**Clerk card** (print it for the judge playing the clerk):

> 1. "Hayes Street Guesthouse." *(the agent explains)*
> 2. "We can hold it, but after 11 there's a forty-dollar late check-in fee." *(the agent says one moment; wait)*
> 3. "Great. The door code is 4-4-1-7, and ask for Maria if anything's wrong."

**Pass rate.** Log every run until you have 5 in a row (the **8:00 PM milestone**):

| Run | Rang | AI line first | Paused on fee | Approval reached the call | Glasses showed Room held | Notes |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |

Also try a Swipe instead of Hold once: the agent should decline the fee and ask whether the room can still be held.

## 9. Save recorded calls for the fallback

After a clean run: ElevenLabs → Call history → open the call → download the audio. Save it as `dashboard/recorded-call.mp3`, replacing the placeholder, and commit it. The dashboard's **Play recorded call** button plays that file. Ask whoever played the clerk before you keep their voice in the repo.

Keep a second good call as `dashboard/recorded-call-2.mp3` in case the first one has a stumble.

## Troubleshooting

| Symptom | Check |
|---|---|
| No ring, dashboard shows `call.completed` with an `error` | The error text says why: wrong key (401), bad IDs (404/422), `to_number` not E.164. Twilio Console → Monitor → Logs → Calls shows whether Twilio tried |
| Glasses show "Call didn't connect" | ElevenLabs or Twilio refused the call; the dashboard call panel shows why. `Account not allowed to call` is Twilio error 21216: check Voice geo permissions, then try another destination phone |
| The callee hears a trial message | The Twilio account isn't upgraded |
| Silence or garbled audio | The native integration sets the audio format itself. If not, set the TTS output format and the user input audio format to μ-law 8000 Hz |
| Agent reads `{{eta}}` aloud | A variable name doesn't match exactly, or the engine isn't sending it |
| Tool call fails | Open `https://<ENGINE_HOST>/state` in a browser. If the tunnel restarted, the host changed: update both tool URLs and the webhook URL |
| Agent gives up before the wearer answers | The engine is older than `p1-engine` and ignores `wait_s` (see step 3). Meanwhile, the clerk keeps talking for a beat, or use the README fallback "Fees up to $30 OK?" |
| Glasses stuck on "Calling guesthouse" after hang-up | The webhook didn't reach the engine: wrong URL, wrong `ELEVENLABS_WEBHOOK_SECRET` (engine logs show 401), or Reset was pressed during the call |
| "Room held / Door code on phone" | The code wasn't verified. The dashboard call panel lists the issues; with no `ANTHROPIC_API_KEY` it says "not checked" |
