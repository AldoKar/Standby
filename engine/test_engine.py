"""Run from engine/:  python test_engine.py"""
import os
import time

os.environ.setdefault("MOCK_CLERK_DELAY_S", "0.2")
os.environ.setdefault("MOCK_CALL_END_S", "0.2")

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


if __name__ == "__main__":
    with TestClient(app) as client:
        test_glasses_flow(client)
        test_asi1_flow_with_fee_allowance(client)
        test_policy_denies_over_budget(client)
        test_policy_hostile_cases(client)
        test_merchant_payment_request(client)
    print("engine ok")
