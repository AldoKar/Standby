// Engine event → chat line (phone page). Longer than the lens copy; the lens copy comes from hud.screen.
import type { EngineEvent } from '../engine/types'

export type ChatRole = 'user' | 'agent' | 'system'
export type ChatLine = { role: ChatRole; text: string }

/** "21:15" → "9:15 PM". */
export function formatTime(hhmm: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm)
  if (!m) return hhmm
  const h = Number(m[1])
  return `${h % 12 || 12}:${m[2]} ${h >= 12 ? 'PM' : 'AM'}`
}

const usd = (n: number) => `$${Number.isInteger(n) ? n : n.toFixed(2)}`

export function eventToChat(e: EngineEvent): ChatLine | null {
  switch (e.type) {
    case 'flight.cancelled': {
      const o = e.data.airline_offer
      return {
        role: 'agent',
        text: `${e.data.flight} (${e.data.route}) was cancelled. ${o.airline} offers ${o.flight} at ${formatTime(o.departs)} ${o.day}. Tap on the glasses and I'll fix tonight.`,
      }
    }
    case 'options.ranked':
      return {
        role: 'agent',
        text: e.data.options
          .map((o) => `${o.airline} ${formatTime(o.departs)}, ${usd(o.price_usd)}: ${o.verdict} (${o.reason})`)
          .join(' · '),
      }
    case 'mandate.checked':
      return { role: 'system', text: `Mandate ${e.data.result}: ${e.data.reason}` }
    case 'approval.requested':
      return {
        role: 'agent',
        text: `${e.data.merchant} ${usd(e.data.amount)} (${e.data.reason}). Hold on the glasses to OK it, swipe down for no.`,
      }
    case 'approval.granted':
      return { role: 'system', text: `👓 Approved via ${e.data.via}` }
    case 'approval.rejected':
      return { role: 'system', text: `👓 Rejected via ${e.data.via}` }
    case 'payment.executed':
      return { role: 'system', text: `${usd(e.data.amount)} to ${e.data.merchant} · agent token ${e.data.token_id} · ${e.data.reference}` }
    case 'offer.declined':
      return {
        role: 'agent',
        text: `Declined ${e.data.airline}'s ${e.data.flight}, so your ${usd(e.data.refund_usd)} refund is automatic (${e.data.status}).`,
      }
    case 'vault.updated':
      return { role: 'system', text: `Saved to Vault: ${e.data.type.replace('_', ' ')}` }
    case 'cutoff.detected':
      return {
        role: 'agent',
        text: `${e.data.place}'s desk closes at ${formatTime(e.data.closes_at)}, and you'll get there around ${formatTime(e.data.eta)}. I'm calling them.`,
      }
    case 'call.started':
      return { role: 'agent', text: `☎ Standby is calling ${e.data.to} to ${e.data.purpose}.` }
    case 'call.completed': {
      const o = e.data.outcome
      if (o.error) return { role: 'agent', text: `The call failed (${o.error}). Details are on the dashboard.` }
      return {
        role: 'agent',
        text: o.held
          ? `Room held${o.door_code ? `, door code ${o.door_code}` : ''}${o.contact ? `, ask for ${o.contact}` : ''}.${e.data.verified ? ' Checked against the transcript.' : ''}`
          : 'They could not hold the room. Details are on the dashboard.',
      }
    }
    case 'task.resolved':
      return {
        role: 'agent',
        text: `All set: ${e.data.flight ?? 'flight'} tonight, room ${e.data.lodging.held ? 'held' : 'not held'}.`,
      }
    case 'demo.reset':
    case 'state.snapshot':
    case 'hud.screen':
      return null
  }
}
