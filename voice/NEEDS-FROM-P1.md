# Needs from P1 (engine)

From P4, Oct 17. P4 doesn't edit `engine/` or `contract/`; these are the engine changes the call and the dashboard need.

**Status: all done by P1 on `p1-engine` (commit `0288957`), including the `call_failed` screen.** Kept below for reference.

## 1. `call.py`: treat `success: false` as a failed call

Checked against the current ElevenLabs reference for `POST /v1/convai/twilio/outbound-call`: URL, `xi-api-key` header, `agent_id`, `agent_phone_number_id`, `to_number` and `conversation_initiation_client_data.dynamic_variables` are all correct.

Two gaps. The 200 response is `{success, message, conversation_id, callSid}`, and `success: false` means no call was placed, but `start_call` returns it as if the call started, so the engine never publishes the failure and the glasses sit on "Calling guesthouse". And on a 4xx, `raise_for_status()` drops ElevenLabs' error body, so the dashboard can't say why.

```python
async def start_call(dynamic_variables: dict) -> dict:
    payload = {...}  # unchanged
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(OUTBOUND_URL, headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, json=payload)
    if r.is_error:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(f"ElevenLabs did not place the call: {body.get('message')}")
    return body  # success, message, conversation_id, callSid
```

`after_booking` already catches the exception and publishes `call.completed` with `outcome.error`; the dashboard shows that error and highlights **Play recorded call**.

## 2. Let `check_approval` wait for the answer

The voice agent can't sleep between tool calls, so "poll every 3 seconds" really means back-to-back calls that each return `pending` at once; the agent gives up after a few seconds, before the wearer has looked at the glasses. A long-poll fixes it: the tool sends `?wait_s=8` (already in `voice/tools.json`), and the engine holds the request until the wearer answers or the time runs out. Without `wait_s` it behaves as today, so the tests don't change.

```python
@app.get("/call/approval/{approval_id}")
async def call_approval_status(approval_id: str, wait_s: float = 0):
    """Voice tool check_approval. With wait_s, holds the request until the wearer answers or time runs out."""
    a = S.approvals.get(approval_id)
    if not a:
        raise HTTPException(404, f"no approval {approval_id}")
    loop = asyncio.get_running_loop()
    end = loop.time() + min(wait_s, 12)
    while a["status"] == "pending" and loop.time() < end:
        await asyncio.sleep(0.25)
    return {"approval_id": approval_id, "status": a["status"]}
```

Contract: add `?wait_s` to `GET /call/approval/{approval_id}` in `contract/api.md`.

## 3. Serve the dashboard's other files

`GET /` serves only `dashboard/index.html`, so the recorded-call fallback (`dashboard/recorded-call.mp3`) 404s when the dashboard is opened from the engine. One line:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/dashboard", StaticFiles(directory=ROOT / "dashboard"), name="dashboard")
```

The page already tries both `recorded-call.mp3` (opened from disk or another host) and `dashboard/recorded-call.mp3` (served by the engine), and has a file picker as a last resort.

## 4. `GET /tests` for the dashboard's pass-rate panel

The panel calls `GET /tests` and shows "not exposed yet" on a 404. Proposed shape (please add it to `contract/api.md` if it works for you):

```json
{
  "ran_at": "2026-10-18T02:10:00Z",
  "passed": 7,
  "total": 9,
  "cases": [
    {"name": "Card request", "passed": true, "detail": "hard stop; payment link offered"},
    {"name": "Big fee ($90)", "passed": true, "detail": "$90 > $45 left; deny"}
  ]
}
```

`cases` can be the 9 hostile cases in `docs/SPEC.md` plus the happy paths. The panel only needs `passed`, `total` and `cases[].name` / `passed`; `detail` and `ran_at` are shown when present. Writing a JSON file from `test_engine.py` and returning it from the endpoint is enough.

## 5. Smaller things noticed

- **Call failed to start:** `after_booking` publishes `call.completed` with the error but leaves the stage at `calling` and the glasses on "Calling guesthouse". Optional: a screen such as `["Call didn't connect", "Details on your phone"]`. A refused request (item 1) never produces a `call_initiation_failure` webhook, so the webhook doesn't cover this case.

## Already covered by your webhook commit

The voice side now uses your `POST /call/webhook` path: `voice/setup.md` step 5 sets the webhook and secret, and the agent's data collection fields are `held`, `door_code`, `contact`, `fee_usd` to match `call.reported_outcome`. I dropped my `report_outcome` tool so the call isn't finished twice. The dashboard shows the check's `summary` and `issues`.
