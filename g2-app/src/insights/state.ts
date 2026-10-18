// Engine events → judge-facing panels (policy trace, phone call, activity), rebuilt from the same SSE
// stream the glasses use. Mirrors what dashboard/index.html (P4) shows, as a pure reducer.
import { formatTime } from '../chat/eventText'
import type { CallOutcome, EngineEvent, EventData, RankedOption } from '../engine/types'

export type SpendCheck = EventData['mandate.checked'] & {
  approval_id?: string
  merchant?: string
  answer?: { ok: boolean; via: string }
}

export type CallStep = { ts: string; text: string }

export type FeedItem = { id: number; ts: string; type: string; text: string }

export type InsightsState = {
  taskId: string | null
  callMode: 'mock' | 'elevenlabs' | ''
  cancelled: EventData['flight.cancelled'] | null
  declined: EventData['offer.declined'] | null
  options: RankedOption[]
  checks: SpendCheck[]
  call: {
    started: boolean
    waiting: boolean // the clerk is on hold while the wearer decides
    steps: CallStep[]
    outcome: CallOutcome | null
    transcriptUrl: string | null
    verified: boolean
  }
  nudge: string | null // tell the presenter to play the recorded call
  feed: FeedItem[]
}

const FEED_MAX = 200
let feedId = 1

export const VIA: Record<string, string> = { glasses: 'the glasses', asi1: 'ASI:One', api: 'the API' }

export const usd = (n: number | null | undefined) =>
  n == null || Number.isNaN(n) ? '' : `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })}`

function emptyCall(): InsightsState['call'] {
  return { started: false, waiting: false, steps: [], outcome: null, transcriptUrl: null, verified: false }
}

export function initialInsights(): InsightsState {
  return { taskId: null, callMode: '', cancelled: null, declined: null, options: [], checks: [], call: emptyCall(), nudge: null, feed: [] }
}

/** Fresh panels for a new task, keeping the activity feed and the call mode. */
function forNewTask(s: InsightsState, taskId: string | null): InsightsState {
  return { ...initialInsights(), taskId, callMode: s.callMode, feed: s.feed }
}

function feedText(e: EngineEvent): string {
  switch (e.type) {
    case 'options.ranked':
      return e.data.options.map((o) => `${o.airline} ${usd(o.price_usd)}: ${o.verdict}`).join(' · ')
    case 'mandate.checked':
      return `${e.data.result} ${e.data.kind} ${usd(e.data.amount)}: ${e.data.reason}`
    case 'payment.executed':
      return `${usd(e.data.amount)} to ${e.data.merchant} · token ${e.data.token_id} · ${e.data.reference}`
    case 'hud.screen':
      return e.data.lines.join(' / ') || '(blank)'
    case 'voice.heard':
      return `"${e.data.transcript}" → ${e.data.intent} (${e.data.via})`
    case 'call.completed':
      return JSON.stringify(e.data.outcome)
    default:
      return e.data && Object.keys(e.data).length ? JSON.stringify(e.data) : ''
  }
}

function step(s: InsightsState, e: EngineEvent, text: string): InsightsState {
  return { ...s, call: { ...s.call, steps: [...s.call.steps, { ts: e.ts, text }] } }
}

function withFeed(s: InsightsState, e: EngineEvent): InsightsState {
  if (e.type === 'state.snapshot') return s
  const item = { id: feedId++, ts: e.ts, type: e.type, text: feedText(e) }
  return { ...s, feed: [item, ...s.feed].slice(0, FEED_MAX) }
}

function apply(s: InsightsState, e: EngineEvent): InsightsState {
  switch (e.type) {
    case 'state.snapshot': {
      const d = e.data
      let next = d.task_id !== s.taskId ? forNewTask(s, d.task_id) : s
      next = { ...next, callMode: d.call_mode ?? next.callMode ?? 'mock' }
      if (d.options?.length) next = { ...next, options: d.options }
      const started = next.call.started || d.stage === 'calling' || d.stage === 'fee'
      const outcome = d.outcome ?? next.call.outcome
      next = {
        ...next,
        call: { ...next.call, started, waiting: d.stage === 'fee', outcome, verified: Boolean(outcome?.verified) },
      }
      if (outcome?.error) next = { ...next, nudge: "The live call didn't start. Play the recorded call." }
      return next
    }
    case 'flight.cancelled': {
      const next = e.task_id !== s.taskId ? forNewTask(s, e.task_id) : s
      return { ...next, cancelled: e.data }
    }
    case 'options.ranked':
      return { ...s, options: e.data.options }
    case 'mandate.checked': {
      let next: InsightsState = { ...s, checks: [...s.checks, { ...e.data }] }
      const d = e.data
      if (d.kind === 'fee' && d.result === 'deny') next = step(next, e, `Clerk asked for ${usd(d.amount)}: denied by the mandate (${d.reason})`)
      if (d.kind === 'fee' && d.result === 'allow') next = step(next, e, `Clerk asked for ${usd(d.amount)}: within the limit, allowed without asking`)
      return next
    }
    case 'approval.requested': {
      const d = e.data
      const checks = [...s.checks]
      for (let i = checks.length - 1; i >= 0; i--) {
        const c = checks[i]
        if (c.kind === d.kind && c.amount === d.amount && !c.approval_id) {
          checks[i] = { ...c, approval_id: d.approval_id, merchant: d.merchant }
          break
        }
      }
      let next: InsightsState = { ...s, checks }
      if (d.kind === 'fee') {
        next = { ...next, nudge: null, call: { ...next.call, waiting: true } }
        next = step(next, e, `Clerk asks +${usd(d.amount)} ${d.reason}. The agent puts the clerk on hold and asks the wearer`)
      }
      return next
    }
    case 'approval.granted':
    case 'approval.rejected': {
      const ok = e.type === 'approval.granted'
      const d = e.data
      const checks = s.checks.map((c) => (c.approval_id === d.approval_id ? { ...c, answer: { ok, via: d.via } } : c))
      let next: InsightsState = { ...s, checks }
      if (d.kind === 'fee') {
        const via = VIA[d.via] ?? d.via
        next = { ...next, call: { ...next.call, waiting: false } }
        next = step(next, e, ok ? `Wearer OK'd the fee on ${via}` : `Wearer said no on ${via}`)
      }
      return next
    }
    case 'payment.executed':
      return s.call.started
        ? step(s, e, `Paid ${usd(e.data.amount)} to ${e.data.merchant} with agent token ${e.data.token_id} (${e.data.reference})`)
        : s
    case 'offer.declined':
      return { ...s, declined: e.data }
    case 'cutoff.detected': {
      const d = e.data
      return step(s, e, `Spotted: ${d.place} desk closes ${formatTime(d.closes_at)}; you land ${formatTime(d.arrival)} and get there around ${formatTime(d.eta)}`)
    }
    case 'call.started': {
      const d = e.data
      const next: InsightsState = { ...s, callMode: d.mode, nudge: null, call: { ...s.call, started: true } }
      return step(next, e, `Calling ${d.to} to ${d.purpose} (${d.mode === 'elevenlabs' ? 'live call, ElevenLabs + Twilio' : 'simulated clerk'})`)
    }
    case 'call.completed': {
      const o = e.data.outcome ?? { held: false }
      let next: InsightsState = {
        ...s,
        nudge: null,
        call: { ...s.call, waiting: false, outcome: o, transcriptUrl: e.data.transcript_url, verified: Boolean(e.data.verified) },
      }
      if (o.error) next = { ...next, nudge: "The live call didn't start. Play the recorded call." }
      else next = step(next, e, 'Call ended')
      if (!o.error && !o.held && next.callMode === 'elevenlabs') {
        next = { ...next, nudge: 'The live call ended without the room held. Need the fallback? Play the recorded call.' }
      }
      return next
    }
    case 'demo.reset':
      return { ...initialInsights(), callMode: s.callMode }
    default:
      return s
  }
}

export function insightsReducer(s: InsightsState, e: EngineEvent): InsightsState {
  const next = apply(s, e)
  return e.type === 'demo.reset' ? next : withFeed(next, e)
}

/** Ledger-affecting events: refetch GET /ledger after these. */
export const LEDGER_EVENTS = new Set([
  'state.snapshot',
  'payment.executed',
  'mandate.checked',
  'offer.declined',
  'approval.granted',
  'approval.rejected',
  'call.completed',
  'demo.reset',
])

/** Live call that hasn't rung after this long → suggest the recorded call. */
export const RING_NUDGE_MS = 10_000
