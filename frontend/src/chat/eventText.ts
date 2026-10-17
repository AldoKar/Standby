// Event → chat message. Longer, conversational version of the same event the lens shows.
import type { Envelope } from '@contracts/events'
import { formatTime } from '../hud/screens'

export type ChatRole = 'user' | 'agent' | 'system'
export type ChatLine = { role: ChatRole; text: string }

export function eventToChat(e: Envelope): ChatLine | null {
  switch (e.type) {
    case 'trip.requested': {
      const { origin, dest, deadline, max_price } = e.data
      return { role: 'system', text: `Trip request: ${origin} → ${dest}, before ${deadline}, max $${max_price}` }
    }
    case 'task.started':
      return {
        role: 'agent',
        text: e.data.kind === 'book' ? 'Searching flights for you…' : 'On it. Looking for alternatives…',
      }
    case 'option.found': {
      const rejected = e.data.rejected.map((r) => `${r.flight} (${r.reason})`).join(', ')
      return {
        role: 'agent',
        text: `I compared ${e.data.options.length} options and picked ${e.data.chosen}.${rejected ? ` Ruled out: ${rejected}.` : ''}`,
      }
    }
    case 'approval.requested': {
      const { flight, departure, arrival, price, reason } = e.data
      return {
        role: 'agent',
        text: `${flight}, ${formatTime(departure)} → ${formatTime(arrival)}, $${price}. ${reason}. Tap on the glasses to approve, hold to skip.`,
      }
    }
    case 'approval.granted':
      return { role: 'system', text: '👓 Approved' }
    case 'approval.rejected':
      return { role: 'system', text: '👓 Rejected' }
    case 'payment.executed':
      return { role: 'agent', text: `Paid $${e.data.amount} ${e.data.currency} with Visa. Ref ${e.data.reference}.` }
    case 'flight.booked': {
      const { flight, departure, arrival, gate } = e.data
      return { role: 'agent', text: `Booked ${flight}, ${formatTime(departure)} → ${formatTime(arrival)}, gate ${gate}.` }
    }
    case 'gate.changed':
      return { role: 'agent', text: `Heads up: ${e.data.flight} moved from gate ${e.data.old_gate} to ${e.data.new_gate}.` }
    case 'boarding.soon':
      return { role: 'agent', text: `${e.data.flight} boards in ${e.data.minutes} min at gate ${e.data.gate}.` }
    case 'flight.cancelled':
      return { role: 'agent', text: `${e.data.flight} (${e.data.route}) was cancelled. Want me to fix it? Tap on the glasses = yes.` }
    case 'call.started':
      return { role: 'agent', text: `☎ Calling ${e.data.provider} on your behalf…` }
    case 'call.completed':
      return { role: 'agent', text: `Call done. Confirmation ${e.data.confirmation}. ${e.data.summary}` }
    case 'task.resolved': {
      const { new_flight, departure, arrival, gate } = e.data
      return {
        role: 'agent',
        text: `✓ Rebooked on ${new_flight}, ${formatTime(departure)} → ${formatTime(arrival)}, gate ${gate}.`,
      }
    }
    case 'task.failed':
      return { role: 'agent', text: `I couldn't finish: ${e.data.reason}` }
    case 'vault.updated':
      return { role: 'system', text: `Saved to Vault: ${e.data.item_type.replace('_', ' ')}` }
  }
}
