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


def test_flight_status_diff():
    from flight_status import diff, normalize
    raw = {"ident_iata": "UA183", "origin": {"code_iata": "LAX", "timezone": "America/Los_Angeles"},
           "destination": {"code_iata": "SFO", "timezone": "America/Los_Angeles"},
           "status": "Scheduled", "cancelled": False, "gate_origin": "52", "departure_delay": 0,
           "scheduled_out": "2026-10-19T01:10:00Z", "scheduled_in": "2026-10-19T02:35:00Z"}
    old = normalize(raw)
    assert old["departure"] == "18:10" and old["route"] == "LAX-SFO"
    assert diff(None, old) == []
    new = normalize({**raw, "gate_origin": "61", "departure_delay": 1800, "estimated_out": "2026-10-19T01:40:00Z"})
    kinds = {k: d for k, d in diff(old, new)}
    assert kinds["gate.changed"] == {"flight": "UA183", "old_gate": "52", "new_gate": "61"}
    assert kinds["flight.delayed"] == {"flight": "UA183", "minutes": 30, "new_departure": "18:40"}
    assert [k for k, _ in diff(old, normalize({**raw, "cancelled": True}))] == ["flight.cancelled"]


if __name__ == "__main__":
    test_payment_guardrails()
    test_cancel_removes_flight_from_search()
    test_flight_status_diff()
    print("backend ok")
