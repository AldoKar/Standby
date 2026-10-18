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
  // Set on the local confirm screen; `of` is the engine screen being approved, `index` the list row (flight list).
  confirm?: { of: HudScreen; index?: number }
  voice?: VoiceState // set by the voice layer (src/voice/listener.ts) on screens that take voice commands
  // Free mode: text alone in the middle of the lens (up to 3 bright lines, no icon). Used by the `answer`
  // screen and the push-to-talk steps.
  center?: boolean
  // Flight list (`flight_list`): three rows in the middle, the highlighted one marked with an arrow.
  list?: boolean
  // Call (`calling`, `call_resumed`): the flight list's boxed layout. Title box ("Calling guesthouse"),
  // phone | text + moving bars, then "Hold = hide" in the footer box (layout.ts planCall).
  call?: boolean
  // Home (`ready`): Standby's logo in the middle, "Ask Standby about your travel" under it, the gestures in the
  // footer box (layout.ts planHome). The engine's "Ready" line isn't shown.
  home?: boolean
  // Set on the local push-to-talk screens; `of` is the engine screen to go back to.
  ask?: { of: HudScreen; phase: AskPhase }
  // Minimized call (hud/callView.ts): only a small phone icon in the corner; `of` is the call screen.
  mini?: { of: HudScreen }
}

export type AskPhase = 'listening' | 'thinking' | 'failed'

/**
 * Shown in the voice tag (top-right corner, see voiceTag below), never in the engine's lines.
 * listening: the mic is open and waiting → "○ Voice on".
 * hearing: speech detected, the wearer is talking right now → "● Listening".
 * thinking: an utterance was sent → "● Heard you".
 * missed: didn't match a command → "? Say again" for a moment.
 * offline: voice unavailable (no key, network, mic) → "Voice off".
 */
export type VoiceState = 'listening' | 'hearing' | 'thinking' | 'missed' | 'offline'

/** Screens the engine accepts voice commands on (contract/api.md "Voice intents per screen"). */
// Everything is tap AND talk, except: `ready` (starting the flow is tap-only, so nearby talk can't start it)
// and the local spend confirm step (paying is always a tap). A voice "yes" on a spend only opens that step.
export const VOICE_SCREENS = new Set([
  'cancelled',
  'declined',
  'booking_offer',
  'only_option',
  'flight_list',
  'fee_request',
  'claim_ready',
  // "OK" / "done" / "back" closes them
  'resolved',
  'not_held',
  'call_failed',
  'claim_submitted',
  'answer',
  // "hide it" / "show it": the call view (hud/callView.ts), done on the glasses
  'calling',
  'call_resumed',
])

/** True when the wearer can answer this screen by voice as well as by tap (spend confirms never). */
export function takesVoice(s: HudScreen): boolean {
  if (s.mini) return VOICE_SCREENS.has(s.mini.of.id) // minimized call: "show it" brings it back
  return VOICE_SCREENS.has(s.id) && !s.confirm
}

/** The engine screen a voice command is for (a minimized call is still the engine's call screen). */
export function engineScreenId(s: HudScreen): string {
  return s.mini ? s.mini.of.id : s.id
}

const VOICE_TAG: Record<VoiceState, string> = {
  listening: '○ Voice on',
  hearing: '● Listening',
  thinking: '● Heard you',
  missed: '? Say again',
  offline: 'Voice off',
}

/**
 * The voice tag: a short, fixed-place label in the top-right corner of every screen that tells the wearer,
 * BEFORE they speak, whether talking does anything here. ≤ 11 characters so it fits next to any title.
 * - voice screens: the live mic state ("○ Voice on" → "● Listening" while they talk → "● Heard you").
 * - the spend confirm step: "Tap only" (voice never approves a spend).
 * - free mode (ready / answer): "Hold = talk" (push-to-talk for a question).
 * - other screens with something to do: "Tap only". Nothing to do (blank, waiting): no tag.
 */
export function voiceTag(s: HudScreen): string {
  // Home: the footer box already says "Hold = ask" / "Tap = start"; Connecting has nothing to do yet.
  if (s.mini || s.home || s.lines.length === 0) return ''
  if (s.confirm) return 'Tap only'
  if (s.ask) return s.ask.phase === 'listening' ? '● Listening' : ''
  if (takesVoice(s)) return VOICE_TAG[s.voice ?? 'listening']
  if (s.gestures.hold === 'ask') return 'Hold = talk'
  return s.choices?.length || Object.keys(s.gestures).length ? 'Tap only' : ''
}

type Style = Pick<HudScreen, 'header' | 'icon' | 'alert' | 'bar' | 'center' | 'list' | 'call' | 'home'>

// Header per screen: only when it adds something the engine's lines don't already say (no brand on every
// screen: it's visual noise). Empty = no header. Never "pay", "card" or "Visa" on the glasses (SPEC).
const STYLES: Record<string, Style> = {
  ready: { header: '', home: true },
  cancelled: { header: '', icon: 'alert', alert: true },
  booking_offer: { header: 'Pick your flight', icon: 'plane' },
  only_option: { header: 'Pick your flight', icon: 'plane' },
  booked: { header: '', icon: 'check' },
  // Boxed like the flight list (layout.ts planCall). Long press minimizes the call to a corner icon
  // (hud/callView.ts); the footer box says so. The wave runs for the whole call.
  calling: { header: '', icon: 'phone', bar: { kind: 'wave' }, call: true },
  call_resumed: { header: '', icon: 'phone', bar: { kind: 'wave' }, call: true },
  fee_request: { header: 'Needs your OK', icon: 'alert', alert: true },
  denied: { header: 'Blocked', icon: 'alert', alert: true },
  no_option: { header: '', icon: 'alert', alert: true },
  resolved: { header: '', icon: 'check' },
  not_held: { header: '', icon: 'alert', alert: true },
  call_failed: { header: '', icon: 'alert', alert: true },
  answer: { header: '', center: true },
  declined: { header: '', icon: 'alert' },
  // Two columns (layout.ts planList): the three flights on the left, the destination on the right.
  flight_list: { header: 'Pick your flight', list: true },
  claim_ready: { header: 'Money back', icon: 'check' },
  claim_submitted: { header: '', icon: 'check' },
}

export const HOME_LINE = 'Ask Standby about your travel'

// Call title: the engine's third `calling` line ("Calling guesthouse"). `call_resumed` (after the fee) is the
// same call and has no such line, so it keeps the last one.
const DEFAULT_CALL_TITLE = 'Calling guesthouse'
let callTitle = DEFAULT_CALL_TITLE

// The engine marks the highlighted row with "> "; the G2 font renders "→" (probed), which reads better.
const LIST_MARK = '→ '

const DEFAULT_STYLE: Style = { header: '', icon: 'none' }

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
    style = { header: '', icon: 'alert', alert: true }
  }
  const lines = [...s.lines]

  // Flight list: up to three rows, no gesture line (the rows use all three lines). The hint comes from the
  // gestures the engine offers: hold books the highlighted flight (tap, then confirm), swipe moves it.
  if (style.list) {
    const rows = lines.slice(0, 3).map((l) => (l.startsWith('> ') ? LIST_MARK + l.slice(2) : l))
    const choices: HudChoice[] = []
    if (s.gestures.hold) choices.push({ gesture: s.gestures.press ? 'hold' : 'tap', label: s.gestures.hold })
    if (s.gestures.swipe_down) choices.push({ gesture: 'swipe', label: s.gestures.swipe_down })
    return { id: s.screen_id, ...style, lines: rows, choices, gestures: s.gestures, tapConfirms: !s.gestures.press }
  }

  // Home: the app's own line under the logo; the gestures the engine offers go in the footer box
  // ("Tap = start · Hold = ask"; just "Tap = start" when free questions are off).
  if (style.home) {
    const choices = GESTURE_ORDER.filter((g) => s.gestures[g]).map((g) => ({ gesture: CAPTION[g], label: s.gestures[g] as string }))
    return { id: s.screen_id, ...style, lines: [HOME_LINE], choices, gestures: s.gestures, tapConfirms: false }
  }

  // Call: title from the engine's third line, the first two in the text column, the hint is app-owned
  // (long press = hide is the glasses' own gesture, hud/callView.ts).
  if (style.call) {
    if (s.screen_id === 'calling') callTitle = lines[2]?.trim() || DEFAULT_CALL_TITLE
    return {
      id: s.screen_id,
      ...style,
      header: callTitle,
      lines: lines.slice(0, 2),
      choices: [{ gesture: 'hold', label: 'hide' }],
      gestures: s.gestures,
      tapConfirms: false,
    }
  }

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

  // Screens that only close (outcome, claim submitted): say how, since there's no gesture line.
  // Voice works here too ("OK", "got it"); the tag shows it.
  const closeOnly = !choices && s.gestures.press === 'dismiss' && Object.keys(s.gestures).length === 1
  const third = lines[2]
  return {
    id: s.screen_id,
    ...style,
    lines: lines.slice(0, 2),
    // With a bar (calling), the third line moves to the footer so it stays visible.
    detail: style.bar ? undefined : third,
    footer: style.bar ? third : undefined,
    choices: choices && choices.length ? choices : closeOnly ? [{ gesture: 'tap', label: 'close' }] : undefined,
    gestures: s.gestures,
    tapConfirms,
  }
}

/**
 * Local "tap again" step before an approval reaches the engine, styled as a dialog: one question, plus a dim
 * recap of what's being approved (the engine's own lines, verbatim) so nobody confirms a spend blind.
 * Tap-only by design: voice never approves a spend. Swipe goes back without sending anything.
 */
export function confirmScreen(of: HudScreen, index?: number): HudScreen {
  const label = of.choices?.find((c) => c.gesture === 'tap')?.label ?? 'confirm'
  const row = index !== undefined ? (of.lines[index] ?? '') : of.lines.find((l) => l.startsWith(LIST_MARK)) ?? ''
  return {
    id: `confirm:${of.id}`,
    header: 'Confirm with a tap',
    icon: 'none',
    alert: true, // the bright card = the dialog box
    dialog: true,
    lines: ['Are you sure?'],
    // e.g. "Delta tonight 9:15 PM · $215 · lands 10:40"; on the list, only the highlighted flight
    detail: of.list ? row.replace(/^(→ |> |\s+)/, '') : of.lines.join(' · '),
    choices: [
      { label, gesture: 'tap' },
      { label: 'back', gesture: 'swipe' },
    ],
    gestures: {},
    tapConfirms: false,
    voice: undefined, // the confirm step is tap-only: spends always need a tap (tag: "Tap only")
    confirm: { of, index },
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
      header: 'Listening',
      lines: ['Ask me anything', 'about your trip'],
      detail: 'Any language',
      choices: [{ gesture: 'tap', label: 'cancel' }],
    }
  }
  if (phase === 'thinking') return { ...base, header: 'Thinking…', lines: ['One moment…'] }
  return { ...base, header: '', lines: [why], choices: [{ gesture: 'hold', label: 'try again' }] }
}

/** While the app connects: the home layout (logo, line under it) so nothing jumps when Ready arrives; the build
 * stamp dim in the footer box (dev, QR sideload and .ehpk look identical otherwise). */
export function idleScreen(build: string): HudScreen {
  return { id: 'boot', header: '', home: true, lines: ['Connecting…'], footer: build, gestures: {} }
}

export function offlineScreen(): HudScreen {
  return {
    id: 'offline',
    header: 'Offline',
    icon: 'alert',
    alert: true,
    lines: ["Can't reach Standby", 'Retrying…'],
    gestures: {},
  }
}

export function gestureFailedScreen(): HudScreen {
  return {
    id: 'gesture_failed',
    header: 'Offline',
    icon: 'alert',
    alert: true,
    lines: ["Didn't reach Standby", 'Try again'],
    gestures: {},
  }
}

/** Plain-text summary for logs and screen readers. */
export function screenSummary(s: HudScreen): string {
  if (s.mini) return 'Call minimized (phone icon in the corner). Long press to show it.'
  const choices = s.choices?.map((c) => `${c.label} (${c.gesture})`) ?? [s.footer]
  return [voiceTag(s), s.header, ...s.lines, s.detail, ...choices].filter(Boolean).join(', ') || 'blank'
}
