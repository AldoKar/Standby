// Local stand-in for backend + Standby agent + monitor (no network).
// Plays the readme.md "Demo event sequence" for real: it waits for taps, enforces the guardrails,
// offers the next option on reject, and fails cleanly when nothing fits.
// Mock data comes from readme.md "Mock data"; the extra booking options are invented for the demo.
import type { Option, TripRequestBody } from '@contracts/events'
import { log } from '../debug/logger'
import { formatTime } from '../hud/screens'
import { makeEvent, publish } from './bus'
import type { SimulateKind, Transport } from './transport'

// ---------- guardrails (mirror of backend/guardrails.py) ----------
const MAX_PURCHASE = 250

// ---------- mock data ----------
const INITIAL_BOOKING = { flight: 'UA183', airline: 'United', origin: 'LAX', dest: 'SFO', departure: '18:10', arrival: '19:35' }
const INITIAL_GATE = '52'
const NEW_GATE = '61'
const DEFAULT_TRIP: TripRequestBody = { origin: 'LAX', dest: 'SFO', deadline: '22:00', max_price: 250 }

const opt = (flight: string, airline: string, departure: string, arrival: string, price: number, refundable = true): Option => ({
  flight, airline, origin: 'LAX', dest: 'SFO', departure, arrival, price, refundable,
})

const BOOK_OPTIONS: Option[] = [
  opt('UA183', 'United', '18:10', '19:35', 189),
  opt('DL410', 'Delta', '17:30', '18:55', 229),
  opt('WN1820', 'Southwest', '19:40', '21:05', 265),
  opt('AS1096', 'Alaska', '20:45', '22:10', 149, false),
]

const RESOLVE_OPTIONS: Option[] = [
  opt('DL412', 'Delta', '19:00', '20:20', 340),
  opt('AS1098', 'Alaska', '21:30', '22:55', 165, false),
  opt('UA927', 'United', '19:15', '20:40', 215),
]

// ---------- state ----------
type Task = {
  kind: 'book' | 'resolve'
  trip: TripRequestBody
  options: Option[]
  candidates: Option[] // valid options, best first
  rejected: { flight: string; reason: string }[]
  index: number
  status: 'searching' | 'awaiting_approval' | 'busy' | 'done'
  approved: boolean
}

const tasks = new Map<string, Task>()
let booking = { ...INITIAL_BOOKING }
let gate = INITIAL_GATE
let cancelledFlight: string | null = null
let lastTrip: TripRequestBody = DEFAULT_TRIP
let epoch = 0 // bumped by reset; every running script stops at its next step
let seq = 0

class Cancelled extends Error {}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Pause inside a script; aborts the script if the demo was reset meanwhile. */
async function step(myEpoch: number, ms: number) {
  await wait(ms)
  if (myEpoch !== epoch) throw new Cancelled('demo reset')
}

/** Simulated network latency for the "HTTP call" itself. */
const latency = () => wait(200)

function run(name: string, script: (myEpoch: number) => Promise<void>) {
  const myEpoch = epoch
  script(myEpoch).catch((err) => {
    if (err instanceof Cancelled) log(`mock: ${name} stopped (${err.message})`)
    else log(`mock: ${name} crashed: ${(err as Error).message}`)
  })
}

// ---------- agent logic ----------
function evaluate(options: Option[], trip: TripRequestBody) {
  const budget = Math.min(trip.max_price, MAX_PURCHASE)
  const rejected: { flight: string; reason: string }[] = []
  const valid: Option[] = []
  for (const o of options) {
    if (o.price > budget) rejected.push({ flight: o.flight, reason: `over $${budget} budget` })
    else if (o.arrival > trip.deadline) rejected.push({ flight: o.flight, reason: `arrives after ${formatTime(trip.deadline)}` })
    else valid.push(o)
  }
  valid.sort((a, b) => a.price - b.price)
  return { valid, rejected }
}

function requestApproval(task_id: string, t: Task) {
  const o = t.candidates[t.index]
  t.status = 'awaiting_approval'
  const reason =
    t.index > 0
      ? 'Next best option'
      : t.kind === 'book'
        ? `Cheapest before ${formatTime(t.trip.deadline)}`
        : `Arrives before ${formatTime(t.trip.deadline)}`
  publish(makeEvent('approval.requested', task_id, {
    flight: o.flight, departure: o.departure, arrival: o.arrival, price: o.price, reason,
  }))
}

async function search(task_id: string, t: Task, myEpoch: number) {
  await step(myEpoch, 1800)
  const { valid, rejected } = evaluate(t.options, t.trip)
  t.candidates = valid
  t.rejected = rejected
  if (valid.length === 0) {
    t.status = 'done'
    publish(makeEvent('task.failed', task_id, { reason: 'No flight fits your budget and deadline' }))
    return
  }
  publish(makeEvent('option.found', task_id, { options: t.options, chosen: valid[0].flight, rejected }))
  await step(myEpoch, 600)
  requestApproval(task_id, t)
}

/** Guardrail-checked payment, like POST /pay. */
function pay(t: Task, amount: number) {
  if (!t.approved) throw new Error('Payment blocked: no approval for this task')
  if (amount > MAX_PURCHASE) throw new Error(`Payment blocked: over $${MAX_PURCHASE} limit`)
  return `VISA-${Math.random().toString(36).slice(2, 6).toUpperCase()}`
}

async function fulfil(task_id: string, t: Task, myEpoch: number) {
  const o = t.candidates[t.index]
  await step(myEpoch, 900)
  let reference: string
  try {
    reference = pay(t, o.price)
  } catch (err) {
    t.status = 'done'
    publish(makeEvent('task.failed', task_id, { reason: (err as Error).message }))
    return
  }
  publish(makeEvent('payment.executed', task_id, { amount: o.price, currency: 'USD', method: 'visa_token', reference }))

  if (t.kind === 'book') {
    await step(myEpoch, 900)
    booking = { flight: o.flight, airline: o.airline, origin: o.origin, dest: o.dest, departure: o.departure, arrival: o.arrival }
    gate = INITIAL_GATE
    cancelledFlight = null
    publish(makeEvent('flight.booked', task_id, { flight: o.flight, departure: o.departure, arrival: o.arrival, gate, price: o.price }))
    await step(myEpoch, 500)
    publish(makeEvent('vault.updated', task_id, { item_type: 'boarding_pass' }))
  } else {
    await step(myEpoch, 800)
    publish(makeEvent('call.started', task_id, { provider: o.airline }))
    await step(myEpoch, 4500)
    const confirmation = Math.random().toString(36).slice(2, 8).toUpperCase()
    publish(makeEvent('call.completed', task_id, {
      confirmation,
      summary: `${o.airline} confirmed your seat on ${o.flight}. The AI assistant identified itself on the call.`,
    }))
    await step(myEpoch, 900)
    booking = { flight: o.flight, airline: o.airline, origin: o.origin, dest: o.dest, departure: o.departure, arrival: o.arrival }
    gate = NEW_GATE
    cancelledFlight = null
    publish(makeEvent('task.resolved', task_id, { new_flight: o.flight, departure: o.departure, arrival: o.arrival, gate }))
    await step(myEpoch, 500)
    publish(makeEvent('vault.updated', task_id, { item_type: 'call_transcript' }))
  }
  t.status = 'done'
}

async function nextOption(task_id: string, t: Task, myEpoch: number) {
  const skipped = t.candidates[t.index]
  t.rejected = [...t.rejected, { flight: skipped.flight, reason: 'you skipped it' }]
  t.index++
  await step(myEpoch, 700)
  if (t.index >= t.candidates.length) {
    t.status = 'done'
    publish(makeEvent('task.failed', task_id, { reason: 'No other flight fits your budget and deadline' }))
    return
  }
  publish(makeEvent('option.found', task_id, { options: t.options, chosen: t.candidates[t.index].flight, rejected: t.rejected }))
  await step(myEpoch, 500)
  requestApproval(task_id, t)
}

const newTaskId = () => `task_${++seq}`

function startTask(task_id: string, kind: 'book' | 'resolve', trip: TripRequestBody, options: Option[]) {
  const t: Task = { kind, trip, options, candidates: [], rejected: [], index: 0, status: 'searching', approved: false }
  tasks.set(task_id, t)
  publish(makeEvent('task.started', task_id, { kind }))
  run(`${kind} ${task_id}`, (e) => search(task_id, t, e))
}

// ---------- transport ----------
export const mockBackend: Transport = {
  async requestTrip(body) {
    await latency()
    lastTrip = body
    // The backend emits trip.requested, then hands the task to the agent.
    const task_id = newTaskId()
    publish(makeEvent('trip.requested', task_id, body))
    startTask(task_id, 'book', body, BOOK_OPTIONS)
  },

  async approve(task_id, approved) {
    await latency()
    const t = tasks.get(task_id)
    if (!t || t.status !== 'awaiting_approval') {
      throw new Error(`No pending approval for ${task_id}`) // backend would answer 409
    }
    t.status = 'busy'
    if (approved) {
      t.approved = true
      publish(makeEvent('approval.granted', task_id, {}))
      run(`fulfil ${task_id}`, (e) => fulfil(task_id, t, e))
    } else {
      publish(makeEvent('approval.rejected', task_id, {}))
      run(`next option ${task_id}`, (e) => nextOption(task_id, t, e))
    }
  },

  async acceptAlert() {
    await latency()
    if (!cancelledFlight) throw new Error('No cancelled flight to fix')
    const busy = [...tasks.values()].some((t) => t.kind === 'resolve' && t.status !== 'done')
    if (busy) throw new Error('Already fixing it')
    // Same deadline/budget the user asked for originally.
    startTask(newTaskId(), 'resolve', { ...lastTrip, origin: booking.origin, dest: booking.dest }, RESOLVE_OPTIONS)
  },

  async simulate(kind: SimulateKind) {
    await latency()
    if (kind === 'gate') {
      if (gate === NEW_GATE) throw new Error(`Gate is already ${NEW_GATE}`)
      publish(makeEvent('gate.changed', null, { flight: booking.flight, old_gate: gate, new_gate: NEW_GATE }))
      gate = NEW_GATE
    } else if (kind === 'boarding') {
      publish(makeEvent('boarding.soon', null, { flight: booking.flight, gate, minutes: 20 }))
    } else {
      if (cancelledFlight) throw new Error(`${cancelledFlight} is already cancelled`)
      cancelledFlight = booking.flight
      publish(makeEvent('flight.cancelled', null, { flight: booking.flight, route: `${booking.origin}-${booking.dest}` }))
    }
  },

  async reset() {
    await latency()
    epoch++
    tasks.clear()
    booking = { ...INITIAL_BOOKING }
    gate = INITIAL_GATE
    cancelledFlight = null
    lastTrip = DEFAULT_TRIP
    log('mock: demo reset')
  },
}
