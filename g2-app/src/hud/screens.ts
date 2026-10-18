// Engine hud.screen → lens screen model (design option B).
// The engine writes every word. This file only decides HOW it looks: which line is bright, which is dim,
// the icon and alert border per screen_id, and turning the gesture line ("Hold = OK, Swipe = no") into
// buttons whose labels come from that same line. The only app-owned text is the small status header
// and the offline/error screens.
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
  bar?: HudBar
  busy?: boolean // open-ended wait → dot spinner (not used by the current engine flow)
  choices?: HudChoice[] // max 2 buttons, each with its gesture below
  gestures: Partial<Record<Gesture, string>> // what the engine accepts on this screen
}

type Style = Pick<HudScreen, 'header' | 'icon' | 'alert' | 'bar'>

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
}
const DEFAULT_STYLE: Style = { header: 'STANDBY', icon: 'none' }

const GESTURE_ORDER: Gesture[] = ['press', 'hold', 'swipe_down']
const CAPTION: Record<Gesture, ChoiceGesture> = { press: 'tap', hold: 'hold', swipe_down: 'swipe' }
const KEYWORD: Record<string, Gesture> = { tap: 'press', press: 'press', hold: 'hold', swipe: 'swipe_down' }
// "Tap = fix it", "Hold to book", "Hold = OK, Swipe = no", "Tap to start"
const PART = /^(tap|press|hold|swipe)(?:\s*down)?\s*(?:=|to)\s*(.+)$/i

const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

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

  // The last line is the gesture hint when it parses as one; it becomes buttons.
  let labels: Partial<Record<Gesture, string>> = {}
  const parsed = lines.length > 1 ? parseGestureLine(lines[lines.length - 1]) : null
  if (parsed) {
    labels = parsed
    lines.pop()
  }
  const offered = GESTURE_ORDER.filter((g) => s.gestures[g])
  const choices = parsed
    ? offered.slice(0, 2).map((g) => ({ gesture: CAPTION[g], label: capitalize(labels[g] ?? s.gestures[g] ?? g) }))
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
  }
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
