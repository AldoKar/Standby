"""Run from engine/:  python test_engine.py"""
import os
import time
from pathlib import Path

os.environ.setdefault("MOCK_CLERK_DELAY_S", "0.2")
os.environ.setdefault("MOCK_CALL_END_S", "0.2")
# Never place real calls from the tests, even if engine/.env says CALL_MODE=elevenlabs
# (app/__init__ loads .env, but variables already set here win).
os.environ["CALL_MODE"] = "mock"

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
    ("Payments signed TAP-style; tampering and replays refused", test_signed_payments),
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
