"""Standby shared contract. Source of truth: readme.md "Shared contract".
Mirror of events.ts — change both together and tell the team.
"""
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, model_validator

# ---------- Shared shapes ----------

class Option(BaseModel):
    flight: str
    airline: str
    origin: str
    dest: str
    departure: str  # "HH:MM"
    arrival: str    # "HH:MM"
    price: float
    refundable: bool


class Rejected(BaseModel):
    flight: str
    reason: str


class Booking(BaseModel):
    flight: str
    origin: str
    dest: str
    date: str       # "YYYY-MM-DD"
    departure: str
    arrival: str
    gate: str
    pnr: str


# ---------- Event payloads (`data`) ----------

class TripRequested(BaseModel):
    origin: str
    dest: str
    deadline: str   # ISO datetime or "HH:MM"
    max_price: float

class TaskStarted(BaseModel):
    kind: Literal["book", "resolve"]

class OptionFound(BaseModel):
    options: list[Option]
    chosen: str
    rejected: list[Rejected] = []

class ApprovalRequested(BaseModel):
    flight: str
    departure: str
    arrival: str
    price: float
    reason: str

class Empty(BaseModel):
    pass

class PaymentExecuted(BaseModel):
    amount: float
    currency: Literal["USD"] = "USD"
    method: Literal["visa_token"] = "visa_token"
    reference: str

class FlightBooked(BaseModel):
    flight: str
    departure: str
    arrival: str
    gate: str
    price: float

class GateChanged(BaseModel):
    flight: str
    old_gate: str
    new_gate: str

class BoardingSoon(BaseModel):
    flight: str
    gate: str
    minutes: int

class FlightCancelled(BaseModel):
    flight: str
    route: str      # "LAX-SFO"

class FlightStatus(BaseModel):     # current snapshot, on request ("what's my flight status?")
    flight: str
    route: str
    status: Optional[str] = None   # "Scheduled", "En Route / On Time", "Cancelled", ...
    cancelled: bool = False
    gate: Optional[str] = None
    terminal: Optional[str] = None
    delay_min: int = 0
    departure: Optional[str] = None
    arrival: Optional[str] = None

class FlightDelayed(BaseModel):
    flight: str
    minutes: int            # total departure delay
    new_departure: str      # "HH:MM" local to origin airport

class CallStarted(BaseModel):
    provider: str

class CallCompleted(BaseModel):
    confirmation: str
    summary: str

class TaskResolved(BaseModel):
    new_flight: str
    departure: str
    arrival: str
    gate: str

class TaskFailed(BaseModel):
    reason: str

class VaultUpdated(BaseModel):
    item_type: Literal["boarding_pass", "receipt", "call_transcript"]


EVENT_DATA: dict[str, type[BaseModel]] = {
    "trip.requested": TripRequested,
    "task.started": TaskStarted,
    "option.found": OptionFound,
    "approval.requested": ApprovalRequested,
    "approval.granted": Empty,
    "approval.rejected": Empty,
    "payment.executed": PaymentExecuted,
    "flight.booked": FlightBooked,
    "gate.changed": GateChanged,
    "boarding.soon": BoardingSoon,
    "flight.cancelled": FlightCancelled,
    "flight.delayed": FlightDelayed,
    "flight.status": FlightStatus,
    "call.started": CallStarted,
    "call.completed": CallCompleted,
    "task.resolved": TaskResolved,
    "task.failed": TaskFailed,
    "vault.updated": VaultUpdated,
}

EventType = Literal[
    "trip.requested", "task.started", "option.found", "approval.requested",
    "approval.granted", "approval.rejected", "payment.executed", "flight.booked",
    "gate.changed", "boarding.soon", "flight.cancelled", "flight.delayed", "flight.status", "call.started",
    "call.completed", "task.resolved", "task.failed", "vault.updated",
]


class Envelope(BaseModel):
    id: str
    type: EventType
    task_id: Optional[str] = None   # null for passive alerts
    ts: str
    data: dict = {}

    @model_validator(mode="after")
    def _check_data(self):
        EVENT_DATA[self.type].model_validate(self.data)
        return self


def make_event(type: str, data: BaseModel | dict | None = None, task_id: str | None = None) -> Envelope:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    return Envelope(
        id=f"evt_{uuid4().hex[:8]}",
        type=type,
        task_id=task_id,
        ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        data=data or {},
    )


# ---------- Backend endpoint bodies ----------

class ApprovalBody(BaseModel):          # POST /approval
    task_id: str
    approved: bool

class AcceptAlertBody(BaseModel):       # POST /accept-alert
    task_id: Optional[str] = None

TripRequestBody = TripRequested         # POST /trip/request

class VaultItemBody(BaseModel):         # POST /vault/items
    type: Literal["boarding_pass", "receipt", "call_transcript"]
    data: dict
    file_url: Optional[str] = None

class PayBody(BaseModel):               # POST /pay (guardrail-checked)
    task_id: str
    amount: float
    merchant: str

class PayResult(BaseModel):
    reference: str

class SearchResult(BaseModel):          # GET /flights/search, tool search_flights
    options: list[Option]


# ---------- Agent wiring ----------

class AgentTask(BaseModel):             # backend -> POST {AGENT_URL}/task
    task_id: str
    kind: Literal["book", "resolve"]
    user_id: str
    input: dict = {}

class FlightAlert(BaseModel):           # monitor -> handle_it (ctx.send)
    flight: str
    status: str                         # "CANCELLED", "GATE_CHANGED", ...


# ---------- Agent tool I/O not covered above ----------

class CallProviderInput(BaseModel):
    provider: str
    goal: str
    context: dict = {}

class CallProviderResult(BaseModel):
    confirmation: str
    new_flight: str
    transcript: str

class SaveToVaultResult(BaseModel):
    id: str


if __name__ == "__main__":
    e = make_event("approval.requested", ApprovalRequested(
        flight="UA927", departure="19:15", arrival="20:40", price=215, reason="Arrives before 10 PM"),
        task_id="task_42")
    assert Envelope.model_validate_json(e.model_dump_json()) == e
    assert set(EVENT_DATA) == set(EventType.__args__)
    try:
        make_event("flight.cancelled", {"flight": "UA183"})  # missing route
        raise SystemExit("validation should have failed")
    except ValueError:
        pass
    print("contract ok")
