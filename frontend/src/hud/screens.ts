// Event → lens screen (what to say). Layout (where it goes) lives in layout.ts.
// Design: fixed 3-zone template — header (dim) · icon + main lines (bright) + detail (dim) · gesture hint (dim).
import type { Envelope } from '@contracts/events'

export type HudAction =
  | { kind: 'approve'; task_id: string }
  | { kind: 'reject'; task_id: string }
  | { kind: 'accept_alert'; task_id: string | null }
  | { kind: 'dismiss' }

export type HudIcon = 'none' | 'search' | 'plane' | 'check' | 'alert' | 'phone' | 'clock'
export type HudBar = { kind: 'progress'; value: number } | { kind: 'wave' }

export type HudScreen = {
  header: string
  lines: string[] // max 2, bright
  detail?: string // dim, below the main lines (hidden when a bar is shown)
  footer?: string // dim, gesture hint or closing note
  icon?: HudIcon
  alert?: boolean // bordered card around the main zone
  bar?: HudBar
  onTap?: HudAction // tap = approve / yes
  onReject?: HudAction // long press = reject / no (double tap is reserved for exit)
}

/** "18:10" → "6:10 PM". Leaves anything unparseable untouched. */
export function formatTime(hhmm: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm)
  if (!m) return hhmm
  const h = Number(m[1])
  return `${h % 12 || 12}:${m[2]} ${h >= 12 ? 'PM' : 'AM'}`
}

export function idleScreen(build: string): HudScreen {
  return { header: 'HANDLE IT', icon: 'plane', lines: ['Ready', 'Ask me from your phone'], footer: build }
}

/** Plain-text summary for logs and screen readers. */
export function screenSummary(s: HudScreen): string {
  return [s.header, ...s.lines, s.detail, s.footer].filter(Boolean).join(', ')
}

const TAP_LONG_GAP = '     '

/**
 * Stateful mapper: some screens depend on earlier events (task kind, trip, rejected options, confirmation).
 * Returns null when an event should not change the lens (chat only).
 */
export function createScreenMapper() {
  const taskKinds = new Map<string, 'book' | 'resolve'>()
  const rejectedCount = new Map<string, number>()
  const confirmations = new Map<string, string>()
  let trip: { origin: string; dest: string; deadline: string; max_price: number } | null = null

  const label = (task_id: string | null) =>
    task_id !== null && taskKinds.get(task_id) === 'resolve' ? 'REBOOKING' : 'BOOKING'

  return function toScreen(e: Envelope): HudScreen | null {
    switch (e.type) {
      case 'trip.requested':
        trip = e.data
        return null

      case 'task.started':
        if (e.task_id) taskKinds.set(e.task_id, e.data.kind)
        return e.data.kind === 'book'
          ? {
              header: 'HANDLE IT · BOOKING',
              icon: 'search',
              lines: [
                'Searching flights…',
                trip ? `${trip.origin} → ${trip.dest} · before ${formatTime(trip.deadline)}` : 'Comparing options',
              ],
              bar: { kind: 'progress', value: 0.35 },
              footer: 'Hang tight, a few seconds',
            }
          : {
              header: 'REBOOKING · SEARCHING',
              icon: 'search',
              lines: ['Finding alternatives…', 'Checking other flights'],
              bar: { kind: 'progress', value: 0.35 },
              footer: 'Hang tight, a few seconds',
            }

      case 'option.found':
        if (e.task_id) rejectedCount.set(e.task_id, e.data.rejected.length)
        return null

      case 'approval.requested': {
        const { flight, departure, arrival, price, reason } = e.data
        const actions: Partial<HudScreen> = e.task_id
          ? { onTap: { kind: 'approve', task_id: e.task_id }, onReject: { kind: 'reject', task_id: e.task_id } }
          : {}
        if (label(e.task_id) === 'REBOOKING') {
          const ruledOut = e.task_id ? (rejectedCount.get(e.task_id) ?? 0) : 0
          const inBudget = trip ? price <= trip.max_price : false
          return {
            header: 'REBOOKING · NEEDS YOUR OK',
            icon: 'plane',
            // Arrival matters when rebooking: the question is "do I still make it before the deadline?"
            lines: [`${flight} · lands ${formatTime(arrival)}`, `$${price}${inBudget ? ' · within budget' : ''}`],
            detail: ruledOut > 0 ? `${ruledOut} others ruled out` : reason,
            footer: `Tap = approve${TAP_LONG_GAP}Hold = next`,
            ...actions,
          }
        }
        return {
          header: 'BOOKING · NEEDS YOUR OK',
          icon: 'plane',
          lines: [`${flight} · ${formatTime(departure)}`, `$${price}${trip ? ` · ${trip.origin} → ${trip.dest}` : ''}`],
          detail: reason,
          footer: `Tap = buy${TAP_LONG_GAP}Hold = skip`,
          ...actions,
        }
      }

      case 'approval.granted':
        return { header: `${label(e.task_id)} · APPROVED`, icon: 'check', lines: ['Approved', 'Paying with Visa…'] }
      case 'approval.rejected':
        return { header: `${label(e.task_id)} · SKIPPED`, icon: 'search', lines: ['Skipped', 'Looking for another…'] }
      case 'payment.executed':
        return {
          header: `${label(e.task_id)} · PAID`,
          icon: 'check',
          lines: [`Paid $${e.data.amount}`, `Visa · ref ${e.data.reference}`],
        }

      case 'flight.booked':
        return {
          header: 'BOOKING · DONE',
          icon: 'check',
          lines: [`Booked ${e.data.flight}`, `Gate ${e.data.gate} · ${formatTime(e.data.departure)}`],
          footer: 'Paid with Visa · saved to Vault',
        }

      case 'gate.changed':
        return {
          header: `ALERT · ${e.data.flight}`,
          alert: true,
          icon: 'alert',
          lines: ['Gate changed', `${e.data.old_gate} → ${e.data.new_gate}`],
          footer: 'No action needed',
        }

      case 'boarding.soon':
        return {
          header: `${e.data.flight} · BOARDING`,
          icon: 'clock',
          lines: [`Boarding in ${e.data.minutes} min`, `Gate ${e.data.gate}`],
          footer: 'No action needed',
        }

      case 'flight.cancelled':
        return {
          header: `ALERT · ${e.data.flight}`,
          alert: true,
          icon: 'alert',
          lines: [`${e.data.flight} CANCELLED`, 'Want me to fix it?'],
          footer: `Tap = yes${TAP_LONG_GAP}Hold = no`,
          onTap: { kind: 'accept_alert', task_id: e.task_id },
          onReject: { kind: 'dismiss' },
        }

      case 'call.started':
        return {
          header: 'REBOOKING · ON THE PHONE',
          icon: 'phone',
          lines: [`Calling ${e.data.provider}…`, 'Confirming your seat'],
          bar: { kind: 'wave' },
          footer: "I'll tell you when it's done",
        }

      case 'call.completed':
        if (e.task_id) confirmations.set(e.task_id, e.data.confirmation)
        return {
          header: 'REBOOKING · ON THE PHONE',
          icon: 'check',
          lines: ['Call done', `Conf. ${e.data.confirmation}`],
        }

      case 'task.resolved': {
        const conf = e.task_id ? confirmations.get(e.task_id) : undefined
        return {
          header: 'REBOOKING · DONE',
          icon: 'check',
          lines: [`Rebooked ${e.data.new_flight}`, `Gate ${e.data.gate} · ${formatTime(e.data.departure)}`],
          footer: conf ? `Conf. ${conf} · saved to Vault` : 'Saved to Vault',
        }
      }

      case 'task.failed':
        return {
          header: `${label(e.task_id)} · STOPPED`,
          alert: true,
          icon: 'alert',
          lines: ["Couldn't finish", e.data.reason],
          footer: 'Details in the chat',
        }

      case 'vault.updated':
        return null
    }
  }
}
