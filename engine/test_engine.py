"""Run from engine/:  python test_engine.py"""
import os
import time
from pathlib import Path

os.environ.setdefault("MOCK_CLERK_DELAY_S", "0.2")
os.environ.setdefault("MOCK_CALL_END_S", "0.2")
# Never place real calls from the tests, even if engine/.env says CALL_MODE=elevenlabs
# (app/__init__ loads .env, but variables already set here win).
os.environ["CALL_MODE"] = "mock"
os.environ["FLIGHTS_MODE"] = "mock"  # nor real flight orders
os.environ["AGENT_MODE"] = "off"  # nor Claude calls (test_agent stubs it)
os.environ["LIVE_FLIGHT"] = "off"  # nor FlightAware lookups (test_free_mode stubs it)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def wait_for(c, stage, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get("/state").json()
        if s["stage"] == stage:
            return s
        time.sleep(0.1)
    raise AssertionError(f"never reached {stage}; last: {s['stage']}")


def test_glasses_flow(c):
    c.post("/demo/reset")
    assert c.post("/input", json={"gesture": "press"}).json()["stage"] == "cancelled"
    s = c.get("/state").json()
    verdicts = {o["airline"]: o["verdict"] for o in s["options"]}
    assert verdicts == {"United": "rejected", "American": "rejected", "Delta": "pick"}
    assert c.post("/input", json={"gesture": "press"}).json()["stage"] == "offer"
    assert c.get("/state").json()["screen"]["lines"] == ["Delta tonight 9:15 PM", "$215 · lands 10:40", "Hold to book"]
    c.post("/input", json={"gesture": "hold"})
    s = wait_for(c, "fee")
    assert s["screen"]["screen_id"] == "fee_request"
    c.post("/input", json={"gesture": "hold"})
    s = wait_for(c, "resolved")
    assert s["screen"]["lines"] == ["Room held", "Door code 4417"]
    ledger = c.get("/ledger").json()
    assert ledger["spent_usd"] == 255 and ledger["remaining_usd"] == 45 and ledger["net_cost_usd"] == 66
    assert len(ledger["consents"]) == 2


def test_asi1_flow_with_fee_allowance(c):
    c.post("/demo/reset")
    r = c.post("/tasks", json={"source": "asi1"}).json()
    assert r["pick"]["airline"] == "Delta" and r["approval_id"]
    c.post("/approval", json={"approval_id": r["approval_id"], "approved": True, "fee_allowance_usd": 50})
    s = wait_for(c, "resolved")
    assert s["outcome"]["door_code"] == "4417"


def test_policy_denies_over_budget(c):
    c.post("/demo/reset")
    c.post("/tasks", json={})
    a = [x for x in c.get("/state").json()["approvals"] if x["status"] == "pending"][0]
    c.post("/approval", json={"approval_id": a["approval_id"], "approved": True})
    wait_for(c, "fee")
    r = c.post("/call/approval", json={"amount": 90, "reason": "late fee"}).json()
    assert r["status"] == "denied"  # $90 > $85 left
    small = c.post("/call/approval", json={"amount": 20, "reason": "towels"}).json()
    assert small["status"] == "approved"  # under the $25 ask limit


def test_policy_hostile_cases(c):
    """SPEC test cases #8 and #9, plus the other ways a spend must be refused."""
    c.post("/demo/reset")
    fee = lambda **kw: c.post("/call/approval", json={"reason": "fee", **kw}).json()["status"]

    # 8: over-budget flight is rejected, with the reason in the trace
    american = next(o for o in c.get("/flights/search").json()["options"] if o["airline"] == "American")
    assert american["verdict"] == "rejected" and "over" in american["reason"]

    # 9: a small fee goes through silently (no consent asked) and is logged
    assert fee(amount=20) == "approved"
    led = c.get("/ledger").json()
    assert [s["amount"] for s in led["spends"]] == [20] and led["consents"] == []

    # merchant outside the mandate (restaurant, MCC 5812) is denied, logged, and the glasses say why
    assert fee(amount=10, merchant="Diner", mcc="5812") == "denied"
    assert c.get("/ledger").json()["denied"][-1]["merchant"] == "Diner"
    assert c.get("/state").json()["screen"]["lines"][1] == "Merchant not allowed"

    # negative, zero and garbage requests never pass or change the budget
    assert fee(amount=-100) == "denied"
    assert fee(amount=0) == "denied"
    assert fee(amount=10, mcc="abc") == "denied"
    assert c.get("/ledger").json()["remaining_usd"] == 280

    # expired mandate denies everything
    c.post("/mandate", json={"expires_hours": -1})
    assert fee(amount=5) == "denied"
    assert c.get("/state").json()["screen"]["lines"][1] == "Spending limit expired"
    c.post("/demo/reset")


def test_merchant_payment_request(c):
    c.post("/demo/reset")
    charge = lambda amount, mcc="7011": c.post("/merchant/payment-request",
                                              json={"merchant": "Guesthouse", "amount": amount, "mcc": mcc})
    # small charge: allowed silently and logged
    assert charge(10).status_code == 200
    assert [s["amount"] for s in c.get("/ledger").json()["spends"]] == [10]
    # over the ask limit with no approval, or outside the mandate: refused and logged
    assert charge(40).status_code == 403
    assert charge(10, mcc="5812").status_code == 403
    assert len(c.get("/ledger").json()["denied"]) == 2

    # an approved booking can be charged exactly once, without counting it twice against the budget
    c.post("/demo/reset")
    r = c.post("/tasks", json={}).json()
    c.post("/approval", json={"approval_id": r["approval_id"], "approved": True})
    pick = r["pick"]
    delta = lambda: c.post("/merchant/payment-request",
                           json={"merchant": pick["airline"], "amount": pick["price_usd"], "mcc": pick["mcc"]})
    assert delta().status_code == 200
    assert delta().status_code == 403
    assert c.get("/ledger").json()["spent_usd"] == pick["price_usd"]
    c.post("/demo/reset")


def test_call_outcome_verification(c):
    """The model is faked here; the real call is tried with `python -m app.verify`."""
    from app import verify
    reported = {"held": True, "door_code": "4417", "contact": "Maria", "fee_usd": 40}
    real = (verify.enabled, verify.extract)
    try:
        verify.enabled = lambda: True

        # The model confirms and the code was said: shown on the glasses
        async def ok(transcript, rep):
            return {**rep, "verified": True, "issues": [], "summary": "Room held."}
        verify.extract = ok
        c.post("/demo/reset")
        r = c.post("/call/completed", json={**reported, "transcript": "Clerk: Door code is 4417."}).json()
        assert r["outcome"]["verified"] and c.get("/state").json()["screen"]["lines"] == ["Room held", "Door code 4417"]

        # SPEC #6: code retracted, the model marks it unverified: no code on the glasses
        async def retracted(transcript, rep):
            return {**rep, "door_code": None, "verified": False, "issues": ["code retracted"], "summary": ""}
        verify.extract = retracted
        c.post("/call/completed", json={**reported, "transcript": "Clerk: It's 4417... never mind."})
        assert c.get("/state").json()["screen"]["lines"] == ["Room held", "Door code on phone"]

        # The model claims verified, but the code was never spoken: code still blocks it
        async def made_up(transcript, rep):
            return {**rep, "door_code": "9999", "verified": True, "issues": [], "summary": ""}
        verify.extract = made_up
        r = c.post("/call/completed", json={**reported, "transcript": "Clerk: Door code is 4417."}).json()
        assert r["outcome"]["door_code"] is None and not r["outcome"]["verified"]

        # Model down: the outcome is never verified, so no code is shown
        async def down(transcript, rep):
            raise RuntimeError("verification stopped: refusal")
        verify.extract = down
        r = c.post("/call/completed", json={**reported, "transcript": "Clerk: Door code is 4417."}).json()
        assert not r["outcome"]["verified"]
        assert c.get("/state").json()["screen"]["lines"] == ["Room held", "Door code on phone"]
    finally:
        verify.enabled, verify.extract = real
        c.post("/demo/reset")


def test_elevenlabs_webhook(c):
    import hashlib, hmac, json as _json
    from app import verify
    secret = os.environ["ELEVENLABS_WEBHOOK_SECRET"] = "whsec_test"
    c.post("/demo/reset")
    c.post("/tasks", json={})
    task_id = c.get("/state").json()["task_id"]

    def send(task, sig_secret=secret, ts=None):
        body = _json.dumps({"type": "post_call_transcription", "data": {
            "transcript": [{"role": "agent", "message": "Hi, I'm an AI assistant calling for Alex."},
                           {"role": "user", "message": "Room is held. Door code is 4417."}],
            "conversation_initiation_client_data": {"dynamic_variables": {"task_id": task}},
            "analysis": {"data_collection_results": {"held": {"value": True}, "door_code": {"value": "4417"}}}}})
        t = str(ts or int(time.time()))
        sig = hmac.new(sig_secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
        return c.post("/call/webhook", content=body, headers={"elevenlabs-signature": f"t={t},v0={sig}"})

    assert send(task_id, sig_secret="wrong").status_code == 401  # forged
    assert send(task_id, ts=int(time.time()) - 3600).status_code == 401  # replayed after 30 min
    assert send("task-old").json().get("ignored")  # a call from before a reset

    real = (verify.enabled, verify.extract)
    try:
        verify.enabled = lambda: True

        async def ok(transcript, rep):
            assert "Clerk: Room is held. Door code is 4417." in transcript
            return {**rep, "contact": None, "fee_usd": None, "verified": True, "issues": [], "summary": ""}
        verify.extract = ok
        assert send(task_id).status_code == 200
        s = wait_for(c, "resolved")
        assert s["screen"]["lines"] == ["Room held", "Door code 4417"]
    finally:
        verify.enabled, verify.extract = real
        c.post("/demo/reset")


def test_call_failure_and_long_poll(c):
    import threading
    c.post("/demo/reset")
    c.post("/tasks", json={})
    a = [x for x in c.get("/state").json()["approvals"] if x["status"] == "pending"][0]
    # long-poll: the check waits for the wearer instead of returning "pending" at once
    threading.Timer(0.5, lambda: c.post("/approval", json={"approval_id": a["approval_id"], "approved": False})).start()
    t = time.time()
    r = c.get(f"/call/approval/{a['approval_id']}?wait_s=5").json()
    assert r["status"] == "rejected" and time.time() - t < 4
    # without wait_s it answers at once (unchanged behavior)
    assert c.get(f"/call/approval/{a['approval_id']}").json()["status"] == "rejected"

    # a call that never connects ends on a clear screen, not "Calling guesthouse"
    import hashlib, hmac, json as _json
    os.environ["ELEVENLABS_WEBHOOK_SECRET"] = "whsec_test"
    task_id = c.get("/state").json()["task_id"]
    body = _json.dumps({"type": "call_initiation_failure",
                        "data": {"conversation_initiation_client_data": {"dynamic_variables": {"task_id": task_id}}}})
    ts = str(int(time.time()))
    sig = hmac.new(b"whsec_test", f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    c.post("/call/webhook", content=body, headers={"elevenlabs-signature": f"t={ts},v0={sig}"})
    s = wait_for(c, "resolved")
    assert s["screen"]["lines"] == ["Call didn't connect", "Details on your phone"]
    c.post("/demo/reset")


def test_stale_gestures_and_not_held(c):
    c.post("/demo/reset")
    c.post("/input", json={"gesture": "press", "screen_id": "ready"})
    c.post("/input", json={"gesture": "press", "screen_id": "cancelled"})
    assert c.get("/state").json()["screen"]["screen_id"] == "booking_offer"

    # a late "hold" from another screen must not book the flight
    r = c.post("/input", json={"gesture": "hold", "screen_id": "fee_request"}).json()
    assert r["handled"] is False and "stale screen" in r["reason"]
    assert c.get("/ledger").json()["spends"] == []

    # the same gesture for the screen actually shown goes through
    assert c.post("/input", json={"gesture": "hold", "screen_id": "booking_offer"}).json()["handled"] is True
    assert [s["amount"] for s in c.get("/ledger").json()["spends"]] == [215]

    # a call that ends without the room gets its own screen id, still at stage resolved
    c.post("/call/completed", json={"held": False})
    s = c.get("/state").json()
    assert s["stage"] == "resolved" and s["screen"]["screen_id"] == "not_held"
    assert s["screen"]["lines"] == ["Room not held", "Details on your phone"]
    c.post("/demo/reset")


def test_voice_commands(c):
    """Typed transcripts exercise the keyword path with no network and no OpenRouter key."""
    c.post("/demo/reset")
    c.post("/input", json={"gesture": "press"})  # cancelled
    say = lambda text, screen: c.post("/voice", json={"screen_id": screen, "transcript": text}).json()  # noqa: E731
    # a gesture-less screen and a stale screen do nothing
    assert say("yes", "booking_offer")["reason"].startswith("stale screen")
    r = say("Yes, fix it", "cancelled")
    assert r["intent"] == "fix" and r["via"] == "keywords" and r["handled"] and r["stage"] == "offer"
    # approving a spend by voice never books: it asks for a tap
    r = say("okay", "booking_offer")
    assert r["intent"] == "approve" and r["confirm_required"] and not r["handled"]
    assert c.get("/state").json()["stage"] == "offer" and c.get("/ledger").json()["spent_usd"] == 0
    # "another one" swipes to the other option; unrelated talk is unknown and changes nothing
    assert say("show me another one", "booking_offer")["intent"] == "other_option"
    assert c.get("/state").json()["screen"]["screen_id"] == "only_option"
    os.environ.pop("OPENROUTER_API_KEY", None)
    r = say("what's the weather like in San Francisco tonight", "only_option")
    assert r["intent"] == "unknown" and not r["handled"]
    c.post("/input", json={"gesture": "hold", "screen_id": "only_option"})
    wait_for(c, "fee")
    # "no" on the fee is applied by voice (declining spends nothing)
    r = say("no thanks", "fee_request")
    assert r["intent"] == "reject" and r["handled"]
    wait_for(c, "resolved")
    assert c.get("/ledger").json()["spent_usd"] == 215
    # no audio and no transcript
    c.post("/demo/reset")
    assert c.post("/voice", json={"screen_id": "ready"}).json()["reason"] == "no voice commands on ready"
    c.post("/demo/reset")


def test_voice_model_fallback(c):
    """Jev first; Haiku only when Jev fails or isn't sure; a failure is never reported as "didn't understand".
    The models are stubbed: no network, no cost."""
    import asyncio
    from app import voice

    calls = []
    lines = ["Delta tonight 9:15 PM", "$215 · lands 10:40"]
    allowed = voice.intents_for("booking_offer")
    phrase = "Yeah thanks, book it for me please."  # too long for the keyword path
    real = (voice._ask, voice.INTENT_MODEL, voice.FALLBACK_MODEL, os.environ.get("OPENROUTER_API_KEY"))
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    voice.INTENT_MODEL, voice.FALLBACK_MODEL = "typesafe/jev-1.14", "anthropic/claude-haiku-4.5"

    def stub(answers):
        async def ask(model, transcript, lines_, allowed_):
            calls.append(model)
            a = answers[model]
            if isinstance(a, Exception):
                raise a
            return a
        voice._ask = ask

    try:
        assert voice.is_decisions_model("typesafe/jev-1.14") and not voice.is_decisions_model("anthropic/claude-haiku-4.5")
        # 1. Jev answers confidently: Haiku is never called
        calls.clear(); stub({"typesafe/jev-1.14": ("approve", 0.97)})
        r = asyncio.run(voice.classify(phrase, "booking_offer", lines))
        assert r[:2] == ("approve", 0.97) and r[3] == "typesafe/jev-1.14" and calls == ["typesafe/jev-1.14"]
        # 2. Jev errors (e.g. HTTP 400): Haiku answers, the note says why
        calls.clear(); stub({"typesafe/jev-1.14": voice.IntentError("typesafe/jev-1.14: HTTP 400"),
                             "anthropic/claude-haiku-4.5": ("approve", 0.95)})
        r = asyncio.run(voice.classify(phrase, "booking_offer", lines))
        assert r[0] == "approve" and r[3] == "anthropic/claude-haiku-4.5" and "HTTP 400" in r[4]
        # 3. Jev unsure: Haiku gets a say
        calls.clear(); stub({"typesafe/jev-1.14": ("approve", 0.4), "anthropic/claude-haiku-4.5": ("approve", 0.9)})
        r = asyncio.run(voice.classify(phrase, "booking_offer", lines))
        assert r[0] == "approve" and calls == ["typesafe/jev-1.14", "anthropic/claude-haiku-4.5"]
        # 4. Both fail: unknown, and the reason reaches the glasses as a failure
        stub({"typesafe/jev-1.14": voice.IntentError("jev down"), "anthropic/claude-haiku-4.5": voice.IntentError("haiku down")})
        r = asyncio.run(voice.classify(phrase, "booking_offer", lines))
        assert r[0] == "unknown" and r[4].startswith("intent model failed")
        c.post("/demo/reset")
        c.post("/input", json={"gesture": "press"})
        c.post("/input", json={"gesture": "press"})
        reply = c.post("/voice", json={"screen_id": "booking_offer", "transcript": phrase}).json()
        assert reply["intent"] == "unknown" and reply["reason"].startswith("intent model failed")
        # 5. The keyword path still answers instantly, no model at all
        calls.clear()
        assert asyncio.run(voice.classify("okay", "booking_offer", lines))[:3] == ("approve", 1.0, "keywords")
        assert calls == []
    finally:
        voice._ask, voice.INTENT_MODEL, voice.FALLBACK_MODEL = real[0], real[1], real[2]
        if real[3] is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = real[3]
        c.post("/demo/reset")


def test_signed_payments(c):
    """Every spend carries a TAP-style signature the merchant can check; tampering breaks it."""
    import base64
    from app import tap
    c.post("/demo/reset")
    assert c.post("/call/approval", json={"amount": 20, "reason": "towels"}).json()["status"] == "approved"
    sig = c.get("/ledger").json()["spends"][0]["signature"]
    assert sig["verified"] and sig["tag"] == "agent-payer-auth" and sig["keyid"] == tap.KEY_ID

    # the key directory publishes the matching public key
    jwk = c.get(tap.DIRECTORY_PATH).json()["keys"][0]
    pub = base64.urlsafe_b64decode(jwk["x"] + "==")

    raw, headers = tap.sign("guesthouse.merchant.example", "/agent/pay", {"amount": 40})
    assert tap.verify("guesthouse.merchant.example", "/agent/pay", raw, headers, pub)[0]
    # replaying the same signed request is refused
    assert tap.verify("guesthouse.merchant.example", "/agent/pay", raw, headers, pub) == (False, "replayed nonce")
    # changing the amount, the merchant or the signature breaks it
    raw, headers = tap.sign("guesthouse.merchant.example", "/agent/pay", {"amount": 40})
    assert not tap.verify("guesthouse.merchant.example", "/agent/pay", b'{"amount":400}', headers, pub)[0]
    assert not tap.verify("evil.merchant.example", "/agent/pay", raw, headers, pub)[0]
    forged = {**headers, "Signature": "sig1=:" + base64.b64encode(b"x" * 64).decode() + ":"}
    assert tap.verify("guesthouse.merchant.example", "/agent/pay", raw, forged, pub) == (False, "bad signature")
    c.post("/demo/reset")


def test_vault(c):
    c.post("/demo/reset")
    seeded = c.get("/vault").json()["items"]
    assert [i["type"] for i in seeded] == ["boarding_pass", "lodging_confirmation", "travel_benefits"]
    assert seeded[1]["data"]["confirmation"] == "48213" and all(i["source"] == "traveler" for i in seeded)

    # the glasses flow saves the new boarding pass and the call
    c.post("/input", json={"gesture": "press"})
    c.post("/input", json={"gesture": "press"})
    c.post("/input", json={"gesture": "hold"})
    wait_for(c, "fee")
    c.post("/input", json={"gesture": "hold"})
    wait_for(c, "resolved")
    items = c.get("/vault").json()["items"]
    new_pass, call_log = items[3], items[4]
    assert new_pass["type"] == "boarding_pass" and new_pass["data"]["flight"] == "DL1946"
    assert new_pass["data"]["replaces"] == "UA183"
    assert new_pass["data"]["payment_reference"] and new_pass["source"] == "agent"
    assert call_log["type"] == "call_transcript" and call_log["data"]["door_code"] == "4417" and call_log["data"]["summary"]

    # a real call's transcript is stored with its checked outcome
    c.post("/call/completed", json={"held": False, "transcript": "Clerk: We're full tonight."})
    last = c.get("/vault").json()["items"][-1]
    assert last["data"]["transcript"] == "Clerk: We're full tonight." and last["data"]["held"] is False

    # reset brings back only what the traveler had
    c.post("/demo/reset")
    assert len(c.get("/vault").json()["items"]) == 3


def test_real_call_fee_screen(c):
    """CALL_MODE=elevenlabs: after the wearer OKs the fee, the glasses leave the fee screen
    while the call goes on (no real call is placed: start_call is stubbed)."""
    from app import main as engine

    async def no_call(variables):
        return {"success": True}
    real = (engine.CALL_MODE, engine.start_call)
    engine.CALL_MODE, engine.start_call = "elevenlabs", no_call
    try:
        c.post("/demo/reset")
        for g in ("press", "press", "hold"):
            c.post("/input", json={"gesture": g})
        wait_for(c, "calling")
        # the voice agent asks for the fee mid-call, the wearer holds to OK it
        a = c.post("/call/approval", json={"amount": 40, "reason": "late check-in"}).json()
        assert c.get("/state").json()["screen"]["screen_id"] == "fee_request"
        c.post("/input", json={"gesture": "hold", "screen_id": "fee_request"})
        s = c.get("/state").json()
        assert s["stage"] == "calling" and s["screen"]["screen_id"] == "call_resumed"
        assert s["screen"]["lines"] == ["+$40 OK", "Finishing the call"]
        assert c.get(f"/call/approval/{a['approval_id']}").json()["status"] == "approved"
        # the call ends: the outcome screen replaces it
        c.post("/call/completed", json={"held": True, "door_code": "4417", "verified": True})
        assert c.get("/state").json()["screen"]["lines"] == ["Room held", "Door code 4417"]
    finally:
        engine.CALL_MODE, engine.start_call = real
        c.post("/demo/reset")


def test_live_flights(c):
    """FLIGHTS_MODE=duffel: live fares are ranked with the airline's offer, the booking creates an
    order and its PNR reaches the glasses and the Vault; a Duffel error falls back to mock fares.
    No network: flights.search/book are stubbed."""
    from app import flights

    live = {"id": "off_1", "offer_id": "off_1", "source": "duffel", "airline": "Duffel Airways", "flight": "ZZ100",
            "departs": "23:58", "arrives": "23:59", "day": "today", "stops": 0, "price_usd": 120,
            "currency": "USD", "total_amount": "120.00", "passenger_id": "pas_1", "mcc": "4511"}

    async def search(*_):
        return [live]

    async def book(option):
        assert option["offer_id"] == "off_1"
        return {"order_id": "ord_1", "pnr": "X7K2QZ", "source": "duffel"}

    async def broken(*_):
        raise RuntimeError("duffel 500: down")
    real = (flights.enabled, flights.search, flights.book)
    flights.enabled, flights.search, flights.book = (lambda: True), search, book
    try:
        c.post("/demo/reset")
        c.post("/input", json={"gesture": "press"})
        s = c.get("/state").json()
        assert [o["verdict"] for o in s["options"]] == ["rejected", "pick"] and s["pick"]["flight"] == "ZZ100"
        c.post("/input", json={"gesture": "press"})
        c.post("/input", json={"gesture": "hold"})
        wait_for(c, "calling")
        assert c.get("/vault").json()["items"][3]["data"]["pnr"] == "X7K2QZ"

        flights.search = broken
        c.post("/demo/reset")
        c.post("/input", json={"gesture": "press"})
        assert c.get("/state").json()["pick"]["flight"] == "DL1946"
    finally:
        flights.enabled, flights.search, flights.book = real
        c.post("/demo/reset")


def test_agent_decides(c):
    """AGENT_MODE=claude: Claude's tool calls drive the plan and the arrival call, but policy has the
    last word (a rejected option is refused). No network: agent.run is replaced by a scripted Claude."""
    from app import agent

    async def fake_claude(phase, facts, tools, on_step):
        async def use(name, **i):
            out = await tools[name](i)
            await on_step({"phase": phase, "kind": "tool", "tool": name, "input": i, "result": out, "error": False})
            return out
        if phase == "plan":
            assert (await use("check_flight_status", flight="UA183"))["status"] == "cancelled"
            found = await use("search_flights", origin="LAX", destination="SFO", date="2026-10-18")
            ids = {o["airline"]: o["id"] for o in found["options"]}
            assert "refused" in await use("choose_flight", option_id=ids["American"], reason="nonstop")  # over budget
            assert "chosen" in await use("choose_flight", option_id=ids["Delta"], reason="arrives tonight in budget")
            return "Picked Delta DL1946: lands 10:40 PM, $215."
        assert (await use("check_arrival"))["arrives_after_desk_closes"] is True
        await use("call_lodging", reason="desk closes before the traveler arrives")
        assert "error" in await use("call_lodging", reason="again")  # one call only
        return "Calling the guesthouse to hold the room."

    real = (agent.enabled, agent.run)
    agent.enabled, agent.run = (lambda: True), fake_claude
    try:
        c.post("/demo/reset")
        c.post("/input", json={"gesture": "press"})
        s = c.get("/state").json()
        assert s["pick"]["flight"] == "DL1946" and s["pick"]["chosen_by"] == "agent"
        assert [x["tool"] for x in s["agent"] if x["kind"] == "tool"][:4] == [
            "check_flight_status", "search_flights", "choose_flight", "choose_flight"]
        c.post("/input", json={"gesture": "press"})
        c.post("/input", json={"gesture": "hold"})
        s = wait_for(c, "fee")  # Claude called the guesthouse; the mock clerk asks for the fee
        assert any(x["kind"] == "done" and x["phase"] == "arrival" for x in s["agent"])

        async def broken(*_):
            raise RuntimeError("model down")
        agent.run = broken  # Claude fails: the scripted flow takes over
        c.post("/demo/reset")
        c.post("/input", json={"gesture": "press"})
        assert c.get("/state").json()["pick"]["flight"] == "DL1946"
    finally:
        agent.enabled, agent.run = real
        c.post("/demo/reset")


def test_ask(c):
    """POST /ask: Claude answers with read-only tools; trip flights come from the trip, others from
    FlightAware; the answer shows on the glasses and a tap puts the old screen back, but it never
    covers a screen waiting for a gesture. No network: agent.run and status.fetch are stubbed."""
    import json as j

    from app import agent, status

    seen = {}

    async def fake_claude(phase, facts, tools, on_step, model=None):
        assert phase == "ask" and set(tools) == {"read_vault", "check_flight_status", "read_ledger", "read_task"}
        assert model == agent.ASK_MODEL
        for f in ("UA183", "DL1946", "UA1"):
            seen[f] = await tools["check_flight_status"]({"flight": f})
        seen["vault"] = await tools["read_vault"]({})
        seen["ledger"] = await tools["read_ledger"]({})
        return j.dumps({"answer": "UA1 is delayed 89 minutes, gate G1.", "glasses": ["UA1 delayed 89 min", "Gate G1"]})

    async def live(flight):
        return {"flight": flight, "status": "Delayed", "gate": "G1", "source": "flightaware"}

    real = (agent.enabled, agent.run, status.enabled, status.fetch, agent.can_ask)
    agent.enabled, agent.run, status.enabled, status.fetch = (lambda: True), fake_claude, (lambda: True), live
    agent.can_ask = lambda: True
    try:
        c.post("/demo/reset")
        r = c.post("/ask", json={"question": "Is UA1 on time?"}).json()
        assert r["glasses"] == ["UA1 delayed 89 min", "Gate G1"] and r["shown"]
        assert seen["UA183"]["status"] == "scheduled" and seen["DL1946"]["source"] == "trip"
        assert seen["UA1"]["source"] == "flightaware" and seen["ledger"]["remaining_usd"] == 300
        assert len(seen["vault"]["items"]) == 3
        assert c.get("/state").json()["screen"]["screen_id"] == "answer"
        c.post("/input", json={"gesture": "press"})  # dismiss: back to ready, the flow didn't start
        s = c.get("/state").json()
        assert s["screen"]["screen_id"] == "ready" and s["stage"] == "ready"

        agent.enabled = lambda: False  # scripted plan for this part; /ask itself is still stubbed below
        for g in ("press", "press"):  # booking offer waiting for a hold
            c.post("/input", json={"gesture": g})
        agent.enabled = lambda: True
        r = c.post("/ask", json={"question": "Status of UA183?"}).json()
        assert not r["shown"] and c.get("/state").json()["screen"]["screen_id"] == "booking_offer"
        assert seen["UA183"]["status"] == "cancelled"

        agent.can_ask = lambda: False
        assert c.post("/ask", json={"question": "hi"}).status_code == 503
    finally:
        agent.enabled, agent.run, status.enabled, status.fetch, agent.can_ask = real
        c.post("/demo/reset")


def test_free_mode(c):
    """Free mode: the traveler's flight is a real one (FlightAware, stubbed), a push-to-talk question in any
    language is transcribed without a fixed language and answered by the ask model with live data; Start
    then cancels that same flight. No network."""
    import json as j

    from app import agent, status, voice
    from app import main as engine

    seen = {}

    async def next_departure(origin, dest, prefer="UA", **_):
        assert (origin, dest) == ("LAX", "SFO")
        return {"flight": "UA781", "airline": "UA", "route": "LAX-SFO", "status": "Scheduled",
                "scheduled_departure": "06:00", "date": "2026-10-18", "source": "flightaware",
                "fa_flight_id": "UAL781-1"}

    async def live(flight, fa_flight_id=None):
        seen["fa_flight_id"] = fa_flight_id
        return {"flight": flight, "status": "On time", "gate": "71B", "source": "flightaware"}

    async def stt(audio, fmt="wav", language="en"):
        seen["language"] = language
        return "¿Mi vuelo sale a tiempo?"

    async def fake_claude(phase, facts, tools, on_step, model=None):
        seen.update(model=model, facts=facts, status=await tools["check_flight_status"]({"flight": "UA781"}))
        return j.dumps({"answer": "Tu vuelo UA781 sale a tiempo, puerta 71B.", "glasses": ["UA781 a tiempo", "Puerta 71B"]})

    real = (engine.LIVE_FLIGHT, dict(engine.TRIP), status.enabled, status.next_departure, status.fetch,
            voice.transcribe, agent.can_ask, agent.run)
    engine.LIVE_FLIGHT, status.enabled, status.next_departure, status.fetch = "auto", (lambda: True), next_departure, live
    voice.transcribe, agent.can_ask, agent.run = stt, (lambda: True), fake_claude
    try:
        c.post("/demo/reset")
        c.portal.call(engine.load_live_flight, True)
        s = c.get("/state").json()
        assert s["trip"]["flight"] == "UA781" and s["trip"]["live"] and s["trip"]["departs"] == "06:00"
        assert s["vault"][0]["data"]["flight"] == "UA781"
        assert s["screen"]["gestures"] == {"press": "start", "hold": "ask"}

        r = c.post("/ask", json={"audio": "UklGRg==", "format": "wav"}).json()
        assert r["question"] == "¿Mi vuelo sale a tiempo?" and seen["language"] is None
        assert seen["model"] == agent.ASK_MODEL and seen["status"]["source"] == "flightaware"
        assert seen["facts"]["travelers_flight"]["flight"] == "UA781" and seen["fa_flight_id"] == "UAL781-1"
        assert seen["facts"]["travelers_flight_live_status"]["gate"] == "71B"  # handed over up front
        s = c.get("/state").json()
        assert s["screen"]["screen_id"] == "answer" and s["screen"]["gestures"]["hold"] == "ask"

        c.post("/input", json={"gesture": "press"})  # dismiss the answer: back to free mode
        assert c.post("/input", json={"gesture": "press"}).json()["stage"] == "cancelled"  # Start
        s = c.get("/state").json()
        assert s["screen"]["lines"][0] == "UA781 cancelled"
    finally:
        (engine.LIVE_FLIGHT, trip, status.enabled, status.next_departure, status.fetch,
         voice.transcribe, agent.can_ask, agent.run) = real
        engine.TRIP.clear()
        engine.TRIP.update(trip)
        c.post("/demo/reset")


def test_trip_claim(c):
    """After the trip is handled, the traveler's benefits pay back what they cover: the new fare minus the
    airline refund ($215 - $189 = $26) plus the $40 late fee = $66. Code checks every amount (Claude's
    over-claim of the full fare is refused), nothing is sent until the wearer taps, and the ledger shows it.
    No network: agent.run is a scripted Claude."""
    from app import agent
    from app import main as engine

    def finish_trip():
        for g in ("press", "press", "hold"):
            c.post("/input", json={"gesture": g})
        wait_for(c, "fee")
        c.post("/input", json={"gesture": "hold"})

    def wait_screen(screen_id, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            s = c.get("/state").json()
            if s["screen"]["screen_id"] == screen_id:
                return s
            time.sleep(0.1)
        raise AssertionError(f"never showed {screen_id}; last: {s['screen']['screen_id']}")

    tried = []

    async def fake_claude(phase, facts, tools, on_step):
        if phase != "claim":
            raise RuntimeError("only the claim is scripted here")
        spends = (await tools["read_ledger"]({}))["spends"]
        delta, fee = (next(x["reference"] for x in spends if x["kind"] == k) for k in ("booking", "fee"))
        greedy = await tools["file_claim"]({"items": [
            {"reference": delta, "benefit_id": "trip_interruption", "amount_usd": 215, "reason": "new flight"}],
            "letter": "x"})
        tried.append(greedy)
        ok = await tools["file_claim"]({"items": [
            {"reference": delta, "benefit_id": "trip_interruption", "amount_usd": 26, "reason": "fare difference"},
            {"reference": fee, "benefit_id": "trip_delay", "amount_usd": 40, "reason": "late check-in"}],
            "letter": "Claim for Alex Rivera: UA183 cancelled; $26 fare difference, $40 late check-in."})
        assert ok["claim_ready"] == 66
        return "Your $66 claim is ready to submit."

    real = (engine.CLAIM_DELAY_S, agent.enabled, agent.run)
    engine.CLAIM_DELAY_S = 0.1
    try:
        # scripted (no Claude): same $66, the wearer submits with a tap
        c.post("/demo/reset")
        finish_trip()
        s = wait_screen("claim_ready")
        assert s["screen"]["lines"] == ["Trip claim ready", "$66 back expected", "Tap = submit"]
        assert s["claim"]["status"] == "ready" and s["claim"]["drafted_by"] == "script"
        assert [(i["benefit_id"], i["amount_usd"]) for i in s["claim"]["items"]] == [
            ("trip_interruption", 26), ("trip_delay", 40)]
        assert all(i["receipt"]["signature_verified"] for i in s["claim"]["items"])
        assert s["ledger"]["claims_expected_usd"] == 0  # nothing is sent before the tap
        c.post("/input", json={"gesture": "press", "screen_id": "claim_ready"})
        s = c.get("/state").json()
        assert s["claim"]["status"] == "submitted" and s["screen"]["screen_id"] == "claim_submitted"
        assert s["ledger"]["claims_expected_usd"] == 66 and s["ledger"]["net_after_claims_usd"] == 0
        assert c.get("/vault").json()["items"][-1]["type"] == "trip_claim"

        # Claude drafts it; its over-claim is refused and it fixes it
        agent.enabled, agent.run = (lambda: True), fake_claude
        c.post("/demo/reset")
        finish_trip()  # plan/arrival fail on purpose: the scripted flow takes over
        s = wait_screen("claim_ready")
        assert "more than the $26 allowed" in tried[0]["refused"][0]
        assert s["claim"]["drafted_by"] == "agent" and s["claim"]["total_usd"] == 66
        c.post("/input", json={"gesture": "swipe_down"})  # later: stays ready, nothing submitted
        s = c.get("/state").json()
        assert s["claim"]["status"] == "ready" and s["ledger"]["claims"] == []

        # dismissing the outcome before the claim shows cancels it
        agent.enabled = lambda: False
        engine.CLAIM_DELAY_S = 0.5
        c.post("/demo/reset")
        finish_trip()
        wait_for(c, "resolved")
        c.post("/input", json={"gesture": "press"})
        time.sleep(0.8)
        assert c.get("/state").json()["claim"] is None
    finally:
        engine.CLAIM_DELAY_S, agent.enabled, agent.run = real
        c.post("/demo/reset")


def test_claim_api(c):
    """GET /claim (long-poll until drafted) and POST /claim/submit for the orchestrator: same claim and
    same effect as the tap on the glasses, once only, and never another trip's claim."""
    from app import main as engine

    real = engine.CLAIM_DELAY_S
    engine.CLAIM_DELAY_S = 0.3
    try:
        c.post("/demo/reset")
        assert c.get("/claim").json() == {"claim": None, "drafting": False, "task_id": None, "stage": "ready"}
        assert c.post("/claim/submit", json={}).status_code == 404
        for g in ("press", "press", "hold"):
            c.post("/input", json={"gesture": g})
        wait_for(c, "fee")
        c.post("/input", json={"gesture": "hold"})
        wait_for(c, "resolved")
        r = c.get("/claim", params={"wait_s": 5}).json()  # waits through the drafting
        claim = r["claim"]
        assert claim and claim["status"] == "ready" and claim["total_usd"] == 66 and not r["drafting"]
        assert c.post("/claim/submit", json={"claim_id": "clm-other"}).status_code == 409
        r = c.post("/claim/submit", json={"claim_id": claim["claim_id"]}).json()
        assert r["claim"]["status"] == "submitted" and r["claim"]["submitted_via"] == "asi1"
        assert r["ledger"]["claims_expected_usd"] == 66
        assert c.get("/state").json()["screen"]["screen_id"] == "claim_submitted"  # the glasses follow
        again = c.post("/claim/submit", json={}).json()  # idempotent
        assert len(again["ledger"]["claims"]) == 1
    finally:
        engine.CLAIM_DELAY_S = real
        c.post("/demo/reset")


# Names shown on the dashboard's pass-rate panel (GET /tests). SPEC # refers to docs/SPEC.md test cases.
CASES = [
    ("Glasses flow end to end", test_glasses_flow),
    ("ASI:One flow with fee allowance", test_asi1_flow_with_fee_allowance),
    ("#2 Big fee ($90) denied, #9 small fee allowed", test_policy_denies_over_budget),
    ("#8 Over-budget flight, bad amounts, wrong merchant, expired mandate", test_policy_hostile_cases),
    ("Merchant charges: logged, once per approval", test_merchant_payment_request),
    ("#5/#6 Call outcome checked against transcript", test_call_outcome_verification),
    ("ElevenLabs webhook: signed, current task only", test_elevenlabs_webhook),
    ("#7 Call doesn't connect; approval long-poll", test_call_failure_and_long_poll),
    ("Late gesture can't approve another screen; room not held", test_stale_gestures_and_not_held),
    ("Voice: intents per screen, spend approvals need a tap", test_voice_commands),
    ("Voice: Jev first, Haiku fallback, failures reported", test_voice_model_fallback),
    ("Payments signed TAP-style; tampering and replays refused", test_signed_payments),
    ("Vault: pre-seeded, new pass and call saved, reset restores", test_vault),
    ("Real call: fee screen clears after the wearer answers", test_real_call_fee_screen),
    ("Live flights: Duffel fares, real order PNR, mock fallback", test_live_flights),
    ("Claude decides: tool calls drive the plan, policy has the last word", test_agent_decides),
    ("Ask: free questions, live flight status, never covers a pending approval", test_ask),
    ("Trip claim: benefits pay back $66, code caps amounts, wearer submits", test_trip_claim),
    ("Claim API: long-poll until drafted, submit once, never another trip's claim", test_claim_api),
    ("Free mode: real flight, push-to-talk in any language, Start cancels that flight", test_free_mode),
]
RESULTS = Path(__file__).parent / "test-results.json"

if __name__ == "__main__":
    import json
    import traceback
    from datetime import datetime, timezone

    results = []
    with TestClient(app) as client:
        for name, fn in CASES:
            try:
                fn(client)
                results.append({"name": name, "passed": True, "detail": "ok"})
            except Exception as e:
                detail = str(e) or traceback.format_exc(limit=1).strip().splitlines()[-1]
                results.append({"name": name, "passed": False, "detail": detail[:200]})
                client.post("/demo/reset")
    passed = sum(r["passed"] for r in results)
    RESULTS.write_text(json.dumps({"ran_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                   "passed": passed, "total": len(results), "cases": results}, indent=2))
    for r in results:
        print("PASS" if r["passed"] else "FAIL", r["name"], "" if r["passed"] else f"-> {r['detail']}")
    if passed < len(results):
        raise SystemExit(f"{len(results) - passed} failed")
    print("engine ok")
