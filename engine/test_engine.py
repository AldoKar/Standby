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


if __name__ == "__main__":
    with TestClient(app) as client:
        test_glasses_flow(client)
        test_asi1_flow_with_fee_allowance(client)
        test_policy_denies_over_budget(client)
    print("engine ok")
