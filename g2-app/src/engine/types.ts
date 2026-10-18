// TypeScript view of contract/events.md and contract/api.md (the source of truth is contract/).
// If the contract changes, update this file to match; never the other way around.

export type Gesture = 'press' | 'hold' | 'swipe_down'
/** Also sent to POST /input on `flight_list`: the native list's selection moved (with `index`). */
export type ListGesture = 'select'

/** `hud.screen`: the engine writes all copy; the glasses only render it. */
export interface EngineScreen {
  screen_id: string
  lines: string[] // at most 3; empty = blank screen
  gestures: Partial<Record<Gesture, string>> // gestures that do something on this screen
  clear_after_s: number | null
}

export interface RankedOption {
  id: string
  airline: string
  flight: string
  departs: string
  arrives: string
  day: string
  price_usd: number
  mcc: string
  verdict: 'pick' | 'ok' | 'rejected'
  reason: string
}

export interface CallOutcome {
  held: boolean
  fee_usd?: number | null
  door_code?: string | null
  contact?: string | null
  error?: string
  verified?: boolean
  summary?: string // one sentence from the transcript check (engine/app/verify.py)
  issues?: string[] // warning signs found in the transcript
}

export interface EventData {
  'state.snapshot': {
    task_id: string | null
    stage: string
    screen: EngineScreen
    options?: RankedOption[]
    outcome?: CallOutcome | null
    call_mode?: 'mock' | 'elevenlabs'
  }
  'hud.screen': EngineScreen
  'flight.cancelled': {
    flight: string
    route: string
    airline_offer: { airline: string; flight: string; departs: string; arrives: string; day: string; price_usd: number }
    source: string
  }
  'options.ranked': { options: RankedOption[] }
  'mandate.checked': { kind: string; amount: number; remaining: number; result: 'allow' | 'ask' | 'deny'; reason: string }
  'approval.requested': { approval_id: string; kind: 'booking' | 'fee'; amount: number; merchant: string; reason: string }
  'approval.granted': { approval_id: string; kind: 'booking' | 'fee'; via: string }
  'approval.rejected': { approval_id: string; kind: 'booking' | 'fee'; via: string }
  'payment.executed': { amount: number; merchant: string; mcc: string; token_id: string; reference: string }
  'offer.declined': { airline: string; flight: string; refund_usd: number; status: string }
  'vault.updated': { type: 'boarding_pass' | 'call_transcript'; flight?: string }
  'cutoff.detected': { place: string; closes_at: string; arrival: string; eta: string }
  'call.started': { to: string; purpose: string; mode: 'mock' | 'elevenlabs' }
  'call.completed': { outcome: CallOutcome; transcript_url: string | null; verified: boolean }
  'task.resolved': { flight: string | null; lodging: { held: boolean; door_code: string | null } }
  'voice.heard': { screen_id: string; transcript: string; intent: string; confidence: number; via: string; model?: string | null; note?: string | null }
  'agent.answer': { question: string; answer: string; glasses: string[] }
  'trip.updated': { airline: string; flight: string; route: string; date: string; departs: string; source: string }
  'demo.reset': Record<string, never>
}

export type EngineEventType = keyof EventData

/** Discriminated union: `switch (e.type)` narrows `e.data`. */
export type EngineEvent = {
  [K in EngineEventType]: { type: K; ts: string; task_id: string | null; data: EventData[K] }
}[EngineEventType]

/** POST /input response. */
export interface InputResult {
  handled: boolean
  stage: string
  reason?: string // e.g. "stale screen: booking_offer, now fee_request"
}

/** GET /ledger (engine/app/policy.py Ledger.view). */
export interface Ledger {
  mandate: { instruction: string; budget_usd: number; ask_over_usd: number; token_id: string; label: string }
  spent_usd: number
  remaining_usd: number
  refunds_pending_usd: number
  net_cost_usd: number
  spends: { amount: number; merchant: string; kind: string; reference: string; ts: string; signature?: { verified?: boolean } }[]
  refunds: { amount: number; airline: string; status: string; rule?: string; ts: string }[]
  consents: { approval_id: string; gesture: string; approved: boolean; amount: number; merchant: string; ts: string }[]
  denied: { amount: number; merchant: string; reason: string; ts: string }[]
}

/** GET /tests: the last `python test_engine.py` run. */
export interface TestsResult {
  ran_at?: string
  passed: number
  total: number
  cases: { name: string; passed: boolean; detail?: string }[]
}

/** POST /ask response (free question; the short answer reaches the lens as an `answer` hud.screen). */
export interface AskResult {
  question: string // what was heard (transcribed in any language) or typed
  answer: string // 1-3 sentences, for the phone / web page
  glasses: string[] // the lines the engine put on the `answer` screen
  shown: boolean // false while a spend is waiting: the answer doesn't cover it
}

/** POST /voice response. */
export interface VoiceResult {
  transcript: string
  intent: string // one the screen allows, or "unknown"
  confidence: number
  via: 'keywords' | 'model' | 'none'
  model?: string | null // which model answered (primary or fallback)
  gesture: Gesture | null
  handled: boolean
  confirm_required: boolean // a spend approval: the glasses must ask for a tap
  reason: string | null
  stage: string
}
