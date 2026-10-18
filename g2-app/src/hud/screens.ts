// Engine hud.screen → lens screen model (design option B).
// The engine writes every word. This file only decides HOW it looks: which line is bright, which is dim,
// the icon and alert border per screen_id, and turning the gesture line ("Hold = OK, Swipe = no") into
// one native hint line whose labels come from that same line. The only app-owned text is the small status
// header, the confirm step and the offline/error screens.
import type { EngineScreen, Gesture } from '../engine/types'

export type HudIcon = 'none' | 'search' | 'plane' | 'check' | 'alert' | 'phone' | 'clock'
export type HudBar = { kind: 'wave' }
export type ChoiceGesture = 'tap' | 'hold' | 'swipe'
export type HudChoice = { label: string; gesture: ChoiceGesture }

export type HudScreen = {
  id: string // engine screen_id (sent back with every gesture)
  header: string
  lines: string[] // max 2, bright
  detail?: string // dim, below the main lines (hidden when a bar is shown)
  footer?: string // dim, used when there are no buttons
  icon?: HudIcon
  alert?: boolean // bordered card around the main zone
  dialog?: boolean // confirm dialog: no icon, the question and its recap sit inside the card
  bar?: HudBar
  busy?: boolean // open-ended wait → dot spinner (not used by the current engine flow)
  choices?: HudChoice[] // rendered as one hint line: "Tap = book  ·  Swipe ↓ = other" (replaces `footer`)
  gestures: Partial<Record<Gesture, string>> // what the engine accepts on this screen
  // Tap-then-confirm (SPEC fallback for long press): on screens where the engine offers `hold` = approve but
  // not `press`, a tap opens a local confirm screen; a second tap sends `hold`. Long press still works directly.
  tapConfirms?: boolean
  confirm?: { of: HudScreen } // set on the local confirm screen; `of` is the engine screen being approved
  voice?: VoiceState // set by the voice layer (src/voice/listener.ts) on screens that take voice commands
  // Free mode: text alone in the middle of the lens (up to 3 bright lines, no icon). Used by the `answer`
  // screen and the push-to-talk steps.
  center?: boolean
  // Set on the local push-to-talk screens; `of` is the engine screen to go back to.
  ask?: { of: HudScreen; phase: AskPhase }
}

export type AskPhase = 'listening' | 'thinking' | 'failed'

/**
 * listening: mic verified live → the hint adds "· or say it".
 * thinking: an utterance was sent → header "STANDBY · HEARD YOU…".
 * missed: didn't match a command → header "STANDBY · DIDN'T CATCH THAT" for a moment.
 * offline: voice unavailable (no key, network) → header "STANDBY · VOICE OFF" for a moment.
 */
export type VoiceState = 'listening' | 'thinking' | 'missed' | 'offline'

/** Screens the engine accepts voice commands on (contract/api.md "Voice intents per screen"). */
export const VOICE_SCREENS = new Set(['cancelled', 'booking_offer', 'only_option', 'fee_request'])

type Style = Pick<HudScreen, 'header' | 'icon' | 'alert' | 'bar' | 'center'>

// Status header per screen. Never "pay", "card" or "Visa" on the glasses (SPEC).
const STYLES: Record<string, Style> = {
  ready: { header: 'STANDBY', icon: 'plane' },
  cancelled: { header: 'STANDBY · ALERT', icon: 'alert', alert: true },
  booking_offer: { header: 'STANDBY · NEEDS YOUR OK', icon: 'plane' },
  only_option: { header: 'STANDBY · NEEDS YOUR OK', icon: 'plane' },
  booked: { header: 'STANDBY · BOOKED', icon: 'check' },
  calling: { header: 'STANDBY IS CALLING', icon: 'phone', bar: { kind: 'wave' } },
  fee_request: { header: 'STANDBY · NEEDS YOUR OK', icon: 'alert', alert: true },
  denied: { header: 'STANDBY · BLOCKED', icon: 'alert', alert: true },
  no_option: { header: 'STANDBY', icon: 'alert', alert: true },
  resolved: { header: 'STANDBY · DONE', icon: 'check' },
  answer: { header: 'STANDBY · ANSWER', center: true },
}
const DEFAULT_STYLE: Style = { header: 'STANDBY', icon: 'none' }

const GESTURE_ORDER: Gesture[] = ['press', 'hold', 'swipe_down']
const CAPTION: Record<Gesture, ChoiceGesture> = { press: 'tap', hold: 'hold', swipe_down: 'swipe' }
const KEYWORD: Record<string, Gesture> = { tap: 'press', press: 'press', hold: 'hold', swipe: 'swipe_down' }
// "Tap = fix it", "Hold to book", "Hold = OK, Swipe = no", "Tap to start"
const PART = /^(tap|press|hold|swipe)(?:\s*down)?\s*(?:=|to)\s*(.+)$/i

/** Labels per gesture from the engine's gesture line, or null if the line isn't one. */
function parseGestureLine(line: string): Partial<Record<Gesture, string>> | null {
  const out: Partial<Record<Gesture, string>> = {}
  for (const part of line.split(/\s*,\s*/)) {
    const m = PART.exec(part.trim())
    if (!m) return null
    out[KEYWORD[m[1].toLowerCase()]] = m[2].trim()
  }
  return out
}

export function blankScreen(id = 'idle'): HudScreen {
  return { id, header: '', lines: [], gestures: {} }
}

export function fromEngine(s: EngineScreen): HudScreen {
  if (s.lines.length === 0) return blankScreen(s.screen_id)
  let style = STYLES[s.screen_id] ?? DEFAULT_STYLE
  // `resolved` is also used for the failure ("Room not held"); don't show a success check for it.
  // TODO(P1): a separate screen_id (e.g. `not_held`) would make this explicit.
  if (s.screen_id === 'resolved' && /\bnot\b/i.test(s.lines[0] ?? '')) {
    style = { header: 'STANDBY', icon: 'alert', alert: true }
  }
  const lines = [...s.lines]

  // An answer is all facts (no gesture line): every line bright, in the middle. The hint is app-owned and
  // comes from the gestures the engine offers ("dismiss", and "ask" again in free mode).
  if (style.center) {
    const choices: HudChoice[] = [{ gesture: 'tap', label: 'back' }]
    if (s.gestures.hold === 'ask') choices.push({ gesture: 'hold', label: 'ask again' })
    return { id: s.screen_id, ...style, lines: lines.slice(0, 3), choices, gestures: s.gestures, tapConfirms: false }
  }

  // The last line is the gesture hint when it parses as one; it becomes buttons.
  let labels: Partial<Record<Gesture, string>> = {}
  const parsed = lines.length > 1 ? parseGestureLine(lines[lines.length - 1]) : null
  if (parsed) {
    labels = parsed
    lines.pop()
  }
  const offered = GESTURE_ORDER.filter((g) => s.gestures[g])
  const tapConfirms = Boolean(s.gestures.hold) && !s.gestures.press
  const choices = parsed
    ? offered.slice(0, 2).map((g) => ({
        // With tap-to-confirm, the approve button is labelled with the easier gesture.
        gesture: g === 'hold' && tapConfirms ? ('tap' as const) : CAPTION[g],
        // Engine wording as-is ("fix it", "OK", "no"); `gestures` values fill in what the line doesn't mention.
        label: labels[g] ?? s.gestures[g] ?? g,
      }))
    : undefined

  const third = lines[2]
  return {
    id: s.screen_id,
    ...style,
    lines: lines.slice(0, 2),
    // With a bar (calling), the third line moves to the footer so it stays visible.
    detail: style.bar ? undefined : third,
    footer: style.bar ? third : undefined,
    choices: choices && choices.length ? choices : undefined,
    gestures: s.gestures,
    tapConfirms,
  }
}

/**
 * Local "tap again" step before an approval reaches the engine, styled as a dialog: one question, plus a dim
 * recap of what's being approved (the engine's own lines, verbatim) so nobody confirms a spend blind.
 * Tap-only by design: voice never approves a spend. Swipe goes back without sending anything.
 */
export function confirmScreen(of: HudScreen): HudScreen {
  const label = of.choices?.find((c) => c.gesture === 'tap')?.label ?? 'confirm'
  return {
    id: `confirm:${of.id}`,
    header: 'CONFIRM · ONLY TAP, NO VOICE',
    icon: 'none',
    alert: true, // the bright card = the dialog box
    dialog: true,
    lines: ['Are you sure?'],
    detail: of.lines.join(' · '), // e.g. "Delta tonight 9:15 PM · $215 · lands 10:40"
    choices: [
      { label, gesture: 'tap' },
      { label: 'back', gesture: 'swipe' },
    ],
    gestures: {},
    tapConfirms: false,
    voice: undefined, // the confirm step is tap-only: spends always need a tap
    confirm: { of },
  }
}

/**
 * Push-to-talk steps (free mode). App-owned, like the confirm step: the engine only sees the question.
 * listening: the mic is open for one question. thinking: it was sent. failed: say why, then go back.
 */
export function askScreen(of: HudScreen, phase: AskPhase, why = "Didn't catch that"): HudScreen {
  const base = { id: `ask:${phase}`, icon: 'none' as const, center: true, gestures: {}, tapConfirms: false, ask: { of, phase } }
  if (phase === 'listening') {
    return {
      ...base,
      header: 'STANDBY · LISTENING',
      lines: ['Ask me anything', 'about your trip'],
      detail: 'Any language',
      choices: [{ gesture: 'tap', label: 'cancel' }],
    }
  }
  if (phase === 'thinking') return { ...base, header: 'STANDBY · THINKING…', lines: ['One moment…'] }
  return { ...base, header: 'STANDBY', lines: [why], choices: [{ gesture: 'hold', label: 'try again' }] }
}

export function idleScreen(build: string): HudScreen {
  return { id: 'boot', header: 'STANDBY', icon: 'plane', lines: ['Connecting…'], footer: build, gestures: {} }
}

export function offlineScreen(): HudScreen {
  return {
    id: 'offline',
    header: 'STANDBY · OFFLINE',
    icon: 'alert',
    alert: true,
    lines: ["Can't reach Standby", 'Retrying…'],
    gestures: {},
  }
}

export function gestureFailedScreen(): HudScreen {
  return {
    id: 'gesture_failed',
    header: 'STANDBY · OFFLINE',
    icon: 'alert',
    alert: true,
    lines: ["Didn't reach Standby", 'Try again'],
    gestures: {},
  }
}

/** Plain-text summary for logs and screen readers. */
export function screenSummary(s: HudScreen): string {
  const choices = s.choices?.map((c) => `${c.label} (${c.gesture})`) ?? [s.footer]
  return [s.header, ...s.lines, s.detail, ...choices].filter(Boolean).join(', ') || 'blank'
}
