// Turns a chat message into a backend request. Keyword-based stand-in for the real agent (ASI:One / Claude).
import type { TripRequestBody } from '@contracts/events'
import type { SimulateKind } from '../events/transport'

export type ChatCommand =
  | { kind: 'trip'; body: TripRequestBody }
  | { kind: 'simulate'; what: SimulateKind }
  | { kind: 'reset' }
  | { kind: 'unknown' }

/** "before 10 PM" / "antes de las 9:30" → "22:00" / "21:30". Bare hours < 12 are read as PM (evening flights). */
function parseDeadline(text: string): string | null {
  const m = /(?:before|by|antes de(?: las?)?)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i.exec(text)
  if (!m) return null
  let h = Number(m[1])
  const min = m[2] ?? '00'
  const suffix = m[3]?.toLowerCase()
  if (suffix === 'pm' && h < 12) h += 12
  else if (suffix === 'am' && h === 12) h = 0
  else if (!suffix && h < 12) h += 12
  if (h > 23) return null
  return `${String(h).padStart(2, '0')}:${min}`
}

function parseMaxPrice(text: string): number | null {
  const m = /\$\s?(\d{2,5})|(\d{2,5})\s?(?:usd|dollars|d[oó]lares)/i.exec(text)
  return m ? Number(m[1] ?? m[2]) : null
}

export function parseMessage(text: string): ChatCommand {
  const t = text.toLowerCase()
  if (/\b(reset|reinicia|reiniciar)\b/.test(t)) return { kind: 'reset' }
  if (/\b(cancel|cancelled|cancela|cancelado)\b/.test(t)) return { kind: 'simulate', what: 'cancel' }
  if (/\b(gate|puerta)\b/.test(t)) return { kind: 'simulate', what: 'gate' }
  if (/\b(board|boarding|abordar|abordaje)\b/.test(t)) return { kind: 'simulate', what: 'boarding' }
  if (/\b(sf|sfo|san francisco|flight|vuelo|book|reserva)\b/.test(t)) {
    return {
      kind: 'trip',
      body: {
        origin: 'LAX',
        dest: 'SFO',
        deadline: parseDeadline(text) ?? '22:00',
        max_price: parseMaxPrice(text) ?? 250,
      },
    }
  }
  return { kind: 'unknown' }
}
