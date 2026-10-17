// One sample Envelope per event type, using the README mock data.
// Used by the dev panel and the chat shortcuts until the mock bus (Phase 4) and backend (Phase 5) exist.
import type { Envelope, EventType } from '@contracts/events'
import { makeEvent } from '../events/bus'

const BOOK = 'task_book'
const RESOLVE = 'task_resolve'

export const SAMPLE_EVENTS: Record<EventType, () => Envelope> = {
  'trip.requested': () =>
    makeEvent('trip.requested', BOOK, { origin: 'LAX', dest: 'SFO', deadline: '22:00', max_price: 250 }),
  'task.started': () => makeEvent('task.started', BOOK, { kind: 'book' }),
  'option.found': () =>
    makeEvent('option.found', BOOK, {
      options: [
        { flight: 'UA183', airline: 'United', origin: 'LAX', dest: 'SFO', departure: '18:10', arrival: '19:35', price: 189, refundable: true },
      ],
      chosen: 'UA183',
      rejected: [],
    }),
  'approval.requested': () =>
    makeEvent('approval.requested', BOOK, {
      flight: 'UA183', departure: '18:10', arrival: '19:35', price: 189, reason: 'Cheapest nonstop before 10 PM',
    }),
  'approval.granted': () => makeEvent('approval.granted', BOOK, {}),
  'approval.rejected': () => makeEvent('approval.rejected', BOOK, {}),
  'payment.executed': () =>
    makeEvent('payment.executed', BOOK, { amount: 189, currency: 'USD', method: 'visa_token', reference: 'VISA-8F2K' }),
  'flight.booked': () =>
    makeEvent('flight.booked', BOOK, { flight: 'UA183', departure: '18:10', arrival: '19:35', gate: '52', price: 189 }),
  'gate.changed': () => makeEvent('gate.changed', null, { flight: 'UA183', old_gate: '52', new_gate: '61' }),
  'boarding.soon': () => makeEvent('boarding.soon', null, { flight: 'UA183', gate: '61', minutes: 20 }),
  'flight.cancelled': () => makeEvent('flight.cancelled', null, { flight: 'UA183', route: 'LAX-SFO' }),
  'call.started': () => makeEvent('call.started', RESOLVE, { provider: 'United' }),
  'call.completed': () =>
    makeEvent('call.completed', RESOLVE, { confirmation: 'XK29QP', summary: 'United confirmed the seat on UA927.' }),
  'task.resolved': () =>
    makeEvent('task.resolved', RESOLVE, { new_flight: 'UA927', departure: '19:15', arrival: '20:40', gate: '61' }),
  'task.failed': () => makeEvent('task.failed', RESOLVE, { reason: 'No flights under $250' }),
  'vault.updated': () => makeEvent('vault.updated', BOOK, { item_type: 'boarding_pass' }),
}

export const EVENT_TYPES = Object.keys(SAMPLE_EVENTS) as EventType[]

/** Free-text chat shortcuts → event sequences (replaced by the real agent later). */
export function eventsForMessage(text: string): Envelope[] {
  const t = text.toLowerCase()
  if (/\b(sf|sfo|san francisco|flight|vuelo)\b/.test(t)) {
    return [
      SAMPLE_EVENTS['trip.requested'](),
      SAMPLE_EVENTS['task.started'](),
      SAMPLE_EVENTS['option.found'](),
      SAMPLE_EVENTS['approval.requested'](),
    ]
  }
  if (/\b(gate|puerta)\b/.test(t)) return [SAMPLE_EVENTS['gate.changed']()]
  if (/\b(board|boarding|abordar)\b/.test(t)) return [SAMPLE_EVENTS['boarding.soon']()]
  if (/\b(cancel|cancelled|cancelado)\b/.test(t)) return [SAMPLE_EVENTS['flight.cancelled']()]
  return []
}

/** DEV-only lens screen to check which glyphs the font renders. */
// Letters around each glyph make blank glyphs visible as a gap. Known results (simulator 0.9.5):
// renders √ ★ ☎ → ● ○ · … ↑↓ ▁▃▅▇ — blank ✓ ✔ ☑ ✈ ⚠ ✕ — placeholder box ✅. Icons are images for that reason.
export const GLYPH_PROBE_LINES = ['A✓B A✔B A√B A☑B', 'A★B A✅B A✈B A⚠B', 'A☎B A→B A●B A✕B']

const resolveStart = () => makeEvent('task.started', RESOLVE, { kind: 'resolve' })

/**
 * Named screens from the design mock, each as the event sequence that produces it.
 * Used by the dev panel and by DEV-only `?shot=<name>` for simulator screenshots.
 */
export const DESIGN_SHOTS: Record<string, () => Envelope[]> = {
  searching: () => [SAMPLE_EVENTS['trip.requested'](), SAMPLE_EVENTS['task.started']()],
  'approve-book': () => eventsForMessage('flight'),
  booked: () => [SAMPLE_EVENTS['flight.booked']()],
  gate: () => [SAMPLE_EVENTS['gate.changed']()],
  boarding: () => [SAMPLE_EVENTS['boarding.soon']()],
  cancelled: () => [SAMPLE_EVENTS['flight.cancelled']()],
  'approve-resolve': () => [
    SAMPLE_EVENTS['trip.requested'](),
    resolveStart(),
    makeEvent('option.found', RESOLVE, {
      options: [
        { flight: 'DL412', airline: 'Delta', origin: 'LAX', dest: 'SFO', departure: '19:00', arrival: '20:20', price: 340, refundable: true },
        { flight: 'AS1098', airline: 'Alaska', origin: 'LAX', dest: 'SFO', departure: '21:30', arrival: '22:55', price: 165, refundable: false },
        { flight: 'UA927', airline: 'United', origin: 'LAX', dest: 'SFO', departure: '19:15', arrival: '20:40', price: 215, refundable: true },
      ],
      chosen: 'UA927',
      rejected: [
        { flight: 'DL412', reason: 'over $250 budget' },
        { flight: 'AS1098', reason: 'arrives after 10 PM' },
      ],
    }),
    makeEvent('approval.requested', RESOLVE, {
      flight: 'UA927', departure: '19:15', arrival: '20:40', price: 215, reason: 'Arrives before 10 PM',
    }),
  ],
  calling: () => [resolveStart(), SAMPLE_EVENTS['call.started']()],
  rebooked: () => [resolveStart(), SAMPLE_EVENTS['call.completed'](), SAMPLE_EVENTS['task.resolved']()],
  failed: () => [resolveStart(), SAMPLE_EVENTS['task.failed']()],
}
