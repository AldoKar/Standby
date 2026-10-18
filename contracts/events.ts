// Standby shared contract. Source of truth: readme.md "Shared contract".
// Mirror of events.py — change both together and tell the team.

// ---------- Shared shapes ----------

export interface Option {
  flight: string;
  airline: string;
  origin: string;
  dest: string;
  departure: string; // "HH:MM"
  arrival: string; // "HH:MM"
  price: number;
  refundable: boolean;
}

export interface Booking {
  flight: string;
  origin: string;
  dest: string;
  date: string; // "YYYY-MM-DD"
  departure: string;
  arrival: string;
  gate: string;
  pnr: string;
}

export type VaultItemType = "boarding_pass" | "receipt" | "call_transcript";

// ---------- Events: type -> data ----------

export interface EventData {
  "trip.requested": { origin: string; dest: string; deadline: string; max_price: number };
  "task.started": { kind: "book" | "resolve" };
  "option.found": { options: Option[]; chosen: string; rejected: { flight: string; reason: string }[] };
  "approval.requested": { flight: string; departure: string; arrival: string; price: number; reason: string };
  "approval.granted": Record<string, never>;
  "approval.rejected": Record<string, never>;
  "payment.executed": { amount: number; currency: "USD"; method: "visa_token"; reference: string };
  "flight.booked": { flight: string; departure: string; arrival: string; gate: string; price: number };
  "gate.changed": { flight: string; old_gate: string; new_gate: string };
  "boarding.soon": { flight: string; gate: string; minutes: number };
  "flight.cancelled": { flight: string; route: string };
  "flight.delayed": { flight: string; minutes: number; new_departure: string };
  "flight.status": {
    flight: string; route: string; status: string | null; cancelled: boolean;
    gate: string | null; terminal: string | null; delay_min: number;
    departure: string | null; arrival: string | null;
  };
  "call.started": { provider: string };
  "call.completed": { confirmation: string; summary: string };
  "task.resolved": { new_flight: string; departure: string; arrival: string; gate: string };
  "task.failed": { reason: string };
  "vault.updated": { item_type: VaultItemType };
}

export type EventType = keyof EventData;

/** Discriminated union: `switch (e.type)` narrows `e.data`. */
export type Envelope = {
  [K in EventType]: {
    id: string;
    type: K;
    task_id: string | null; // null for passive alerts
    ts: string; // ISO 8601
    data: EventData[K];
  };
}[EventType];

// ---------- Backend endpoint bodies ----------

export interface ApprovalBody { task_id: string; approved: boolean } // POST /approval
export interface AcceptAlertBody { task_id?: string } // POST /accept-alert
export type TripRequestBody = EventData["trip.requested"]; // POST /trip/request
export interface VaultItemBody { type: VaultItemType; data: unknown; file_url?: string } // POST /vault/items
export interface PayBody { task_id: string; amount: number; merchant: string } // POST /pay
export interface SearchResult { options: Option[] } // GET /flights/search
