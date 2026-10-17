"""Run: python test_backend.py"""
from fastapi.testclient import TestClient

from main import app

c = TestClient(app)


def test_payment_guardrails():
    c.post("/demo/reset")
    assert c.post("/pay", json={"task_id": "t1", "amount": 215, "merchant": "United"}).status_code == 403  # no approval
    c.post("/approval", json={"task_id": "t1", "approved": True})
    assert c.post("/pay", json={"task_id": "t1", "amount": 340, "merchant": "Delta"}).status_code == 403  # over $250
    assert c.post("/pay", json={"task_id": "t1", "amount": 215, "merchant": "United"}).status_code == 200
    assert c.post("/pay", json={"task_id": "t1", "amount": 215, "merchant": "United"}).status_code == 403  # one approval, one payment
    c.post("/approval", json={"task_id": "t2", "approved": False})
    assert c.post("/pay", json={"task_id": "t2", "amount": 100, "merchant": "United"}).status_code == 403  # rejected


def test_cancel_removes_flight_from_search():
    c.post("/demo/reset")
    flights = lambda: [o["flight"] for o in c.get("/flights/search?origin=LAX&dest=SFO").json()["options"]]
    assert "UA183" in flights()
    c.post("/simulate/cancel")
    assert "UA183" not in flights() and "UA927" in flights()


if __name__ == "__main__":
    test_payment_guardrails()
    test_cancel_removes_flight_from_search()
    print("backend ok")
