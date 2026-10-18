// Screen → page plan (where everything goes on the 576×288 lens).
// Single source of truth for BOTH the real glasses (bridge.ts) and the browser mirror (HudMirror.tsx).
//
// Budget: max 12 containers, 8 text, 4 image. Worst case here is 5 text + 2 image
// (margin or alert frame, header, main, detail, footer/hint + icon, bar).
// Choices render as ONE native hint line ("Tap = book  ·  Swipe ↓ = other"), left-aligned like Even's own
// apps, instead of fake buttons: no centring to fake, one read, and the page structure doesn't change between
// screens, so most transitions are cheap textContainerUpgrade calls instead of full rebuilds.
import { destinationArtKey } from './images'
import type { HudChoice, HudScreen, VoiceState } from './screens'

export const LENS_W = 576
export const LENS_H = 288
export const BRIGHT = 4
export const HINT = 3 // gesture hint: readable, but below the facts
export const DIM = 2
export const PADDING = 4
const MAX_CHARS = 40
const HINT_MAX_CHARS = 44

export type TextSpec = {
  id: number
  name: string
  x: number
  y: number
  w: number
  h: number
  color: number // brightness 0..4
  content: string
  border?: boolean
  borderLevel?: number // border brightness 0..15 (default: bridge BORDER_COLOR)
  radius?: number
  padding?: number
  capture?: boolean
  z: number
}

export type ImageSpec = { id: number; name: string; x: number; y: number; w: number; h: number; key: string; z: number }

/**
 * Native list (the glasses draw it and move the selection themselves, with a border on the selected item).
 * `selected` is only for the browser mirror: on the glasses the firmware owns the selection.
 */
export type ListSpec = {
  id: number
  name: string
  x: number
  y: number
  w: number
  h: number
  items: string[]
  selected: number
  border?: boolean
  borderLevel?: number
  radius?: number
  padding?: number
  capture?: boolean
  z: number
}

export type PagePlan = { signature: string; texts: TextSpec[]; images: ImageSpec[]; lists?: ListSpec[] }

// The host may reject empty text containers, so blanks are a single space.
const BLANK = ' '

function clamp(line: string, max = MAX_CHARS): string {
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

// Gesture words on the lens. `↓` is probed and renders on the G2 font.
const GESTURE_WORD: Record<HudChoice['gesture'], string> = { tap: 'Tap', hold: 'Hold', swipe: 'Swipe ↓' }

/** "Tap = book  ·  Swipe ↓ = other" (+ "  ·  or say it" while the mic is live) */
export function hintText(choices: HudChoice[], voice?: VoiceState): string {
  const base = choices.map((c) => `${GESTURE_WORD[c.gesture]} = ${c.label}`).join('  ·  ')
  return voice === 'listening' || voice === 'thinking' ? `${base}  ·  or say it` : base
}

// Voice status lives in the app-owned header, so the engine's lines never move.
const VOICE_HEADER: Partial<Record<VoiceState, string>> = {
  thinking: 'Heard you…',
  missed: "Didn't catch that",
  offline: 'Voice off',
}

const headerText = (s: HudScreen) => (s.voice && VOICE_HEADER[s.voice]) || s.header

/** Image key for centred text: "text:<px>:<gray 0-255>:<uri-encoded text>" (drawn in images.ts). */
export function textImageKey(text: string, px: number, gray: number): string {
  return `text:${px}:${gray}:${encodeURIComponent(text)}`
}

// Flight list: bordered sections, like Even's own menu layout.
//   ┌──────────────── Pick your flight ────────────────┐  title box, the title centred (drawn as an image)
//   ├──────────────────────┬───────────────────────────┤
//   │ ┌Delta 9:15 PM $215┐ │  [destination photo]      │  left: the flights as a NATIVE list: the glasses
//   │  Alaska 9:45 PM $239  │                           │  draw the box on the selected one and move it on
//   │  WN2210 10:00 PM $229 ├───────────────────────────┤  swipe; every move is reported to the engine
//   │                       │ Tap = book                │  (`select`), and a booking carries the row, so
//   │                       │ Swipe ↓ = next            │  what you see selected is what gets booked.
//   └───────────────────────┴───────────────────────────┘
// The separators are borders of the section containers themselves (3 text + 1 list + 2 image containers).
// The list items are the engine's rows without its "> " mark, so they don't change when the highlight moves:
// no rebuild per swipe. A new set of flights (different rows) rebuilds the page.
const SECTION_BORDER = 5 // dim: the lines organise, they don't compete with the flights
const LIST_BOX = { x: 4, y: 56, w: 280, h: 228 }
const ART_BOX = { x: 288, y: 54, w: 284, h: 148 }
const ART = { x: 290, y: 56, w: 280, h: 144 } // inside ART_BOX; 144 = the host's max image height
const HELP_BOX = { x: 288, y: 206, w: 284, h: 78 }

/** The engine's rows ("> Delta…", "  Alaska…") without the highlight mark: stable list items. */
export function listItems(lines: string[]): string[] {
  return lines.slice(0, 3).map((l) => clamp(l.replace(/^(> |→ |\s+)/, ''), 24))
}

/** The row the engine has highlighted (its "> " mark; the screen model turns it into "→ "). */
export function engineHighlight(lines: string[]): number {
  return Math.max(0, lines.findIndex((l) => /^(> |→ )/.test(l)))
}

function planList(s: HudScreen): PagePlan {
  const title = headerText(s)
  const images: ImageSpec[] = [{ id: 7, name: 'art', ...ART, key: destinationArtKey(), z: 7 }]
  if (title) {
    images.unshift({ id: 6, name: 'title', x: (LENS_W - 288) / 2, y: 10, w: 288, h: 36, key: textImageKey(title, 22, 210), z: 6 })
  }
  // One instruction per line in the narrow box; "or say it" joins the first while the mic is live.
  const help = (s.choices ?? []).slice(0, 2).map((c) => `${GESTURE_WORD[c.gesture]} = ${c.label}`)
  if (help.length && (s.voice === 'listening' || s.voice === 'thinking')) help[0] = `${help[0]} · or say it`
  const box = { border: true, borderLevel: SECTION_BORDER, radius: 8 }
  const items = listItems(s.lines)
  return {
    signature: `list:${items.join('|')}`,
    lists: [
      {
        id: 3,
        name: 'flights',
        ...LIST_BOX,
        items,
        selected: engineHighlight(s.lines),
        padding: 8,
        ...box,
        capture: true, // the list is the one container that captures gestures on this page
        z: 3,
      },
    ],
    texts: [
      { id: 1, name: 'titlebox', x: 4, y: 4, w: LENS_W - 8, h: 48, color: DIM, content: BLANK, ...box, z: 1 },
      { id: 2, name: 'artbox', ...ART_BOX, color: DIM, content: BLANK, ...box, z: 2 },
      {
        id: 5,
        name: 'footer',
        ...HELP_BOX,
        color: HINT,
        content: help.map((l) => clamp(l, 24)).join('\n') || BLANK,
        padding: 10,
        ...box,
        z: 5,
      },
    ],
    images,
  }
}

// App margin: a thin, low-brightness outline around the whole app area, so the wearer always knows where
// Standby's space ends and the world begins. Not on alerts (their bright card stands alone) and not on a
// blank lens (quiet by default). Fixed geometry: it never forces a page rebuild between normal screens.
const MARGIN = { x: 4, y: 4, w: LENS_W - 8, h: LENS_H - 8, level: 5, radius: 12 }

// Minimized call: a small phone icon in the top-right corner, nothing else lit. No margin (quiet like a blank
// lens). The capture container stays (blank) so the long press that restores the call still arrives; it sits
// away from the icon so it can't cover it.
const MINI_ICON = { x: LENS_W - 16 - 12 - 32, y: 14, size: 32 }
// A small blinking dot at the icon's top-right, like an apostrophe: the call is still live.
// The container must be at least 20×20 (the glasses reject smaller images and then the WHOLE page fails:
// blank lens, app closed). The dot itself is ~10 px, drawn in the container's top-left corner
// (images.ts), so it sits where it should; the rest of the container is black = unlit. No overlap with the icon.
const MINI_DOT = { x: MINI_ICON.x + MINI_ICON.size + 1, y: MINI_ICON.y - 5, size: 20 }

function planMinimized(): PagePlan {
  return {
    signature: 'mini',
    texts: [{ id: 3, name: 'main', x: 84, y: 84, w: 472, h: 80, color: BRIGHT, content: BLANK, capture: true, z: 3 }],
    images: [
      { id: 6, name: 'icon', x: MINI_ICON.x, y: MINI_ICON.y, w: MINI_ICON.size, h: MINI_ICON.size, key: 'icon:phone', z: 6 },
      { id: 7, name: 'dot', x: MINI_DOT.x, y: MINI_DOT.y, w: MINI_DOT.size, h: MINI_DOT.size, key: 'dot:on', z: 7 },
    ],
  }
}

export function planScreen(s: HudScreen): PagePlan {
  if (s.mini) return planMinimized()
  if (s.list) return planList(s)
  const texts: TextSpec[] = []
  const blank = s.lines.length === 0
  if (s.alert) {
    texts.push({ id: 1, name: 'frame', x: 12, y: 80, w: 552, h: 110, color: DIM, content: BLANK, border: true, z: 1 })
  } else if (!blank) {
    texts.push({
      id: 1,
      name: 'margin',
      x: MARGIN.x,
      y: MARGIN.y,
      w: MARGIN.w,
      h: MARGIN.h,
      color: DIM,
      content: BLANK,
      border: true,
      borderLevel: MARGIN.level,
      radius: MARGIN.radius,
      z: 1, // behind everything
    })
  }
  const hasHint = Boolean(s.choices?.length)
  // Dialog (confirm step): no icon, so the question and its recap start near the card's left edge.
  // Center (free mode answer / push-to-talk): no icon, a 3-row block in the middle of the lens. The SDK can't
  // align text, so a single line gets one blank row above it to sit in the middle row. Fixed geometry, so
  // listening → thinking → answer are cheap text upgrades, not page rebuilds.
  const box = s.dialog
    ? { x: 36, w: 516, mainY: 92, mainH: 40, detailY: 134, detailMax: 46 }
    : s.center
      ? { x: 36, w: 504, mainY: 100, mainH: 96, detailY: 192, detailMax: 46 } // rows are ~28 px on the G2 font
      : { x: 84, w: 472, mainY: 84, mainH: 80, detailY: 158, detailMax: MAX_CHARS }
  const mainLines = s.center ? s.lines.slice(0, 3) : s.lines.slice(0, 2)
  const mainText = mainLines.map((l) => clamp(l)).join('\n')
  const mainContent = s.center && mainLines.length === 1 ? `\n${mainText}` : mainText
  texts.push(
    {
      id: 2,
      name: 'header',
      x: 16,
      y: 12,
      w: 544,
      h: 44,
      color: s.voice && VOICE_HEADER[s.voice] ? HINT : DIM,
      content: clamp(headerText(s)) || BLANK,
      z: 2,
    },
    {
      id: 3,
      name: 'main',
      x: box.x,
      y: box.mainY,
      // Must never overflow: this container captures gestures, and an overflowing text container
      // shows a scroll bar and emits SCROLL events that would read as swipes.
      w: box.w,
      h: box.mainH,
      color: BRIGHT,
      content: mainContent || BLANK,
      capture: true, // exactly one container captures gestures
      z: 3,
    },
    {
      id: 4,
      name: 'detail',
      x: box.x,
      y: box.detailY,
      w: box.w,
      h: 38,
      color: DIM,
      content: (!s.bar && s.detail ? clamp(s.detail, box.detailMax) : '') || BLANK,
      z: 4,
    },
    {
      id: 5,
      name: 'footer',
      x: 16,
      y: 236,
      w: 544,
      h: 44,
      color: hasHint ? HINT : DIM,
      content: (hasHint ? clamp(hintText(s.choices ?? [], s.voice), HINT_MAX_CHARS) : clamp(s.footer ?? '')) || BLANK,
      z: 5,
    },
  )

  // No icon container in the dialog: even an empty (black) image sits above the text and hides
  // the start of "Are you sure?" (z-order), so it must not exist there at all.
  const images: ImageSpec[] =
    s.dialog || s.center
      ? []
      : [{ id: 6, name: 'icon', x: 24, y: 96, w: 48, h: 48, key: `icon:${s.icon ?? 'none'}`, z: 6 }]
  if (s.bar) {
    images.push({ id: 7, name: 'bar', x: 92, y: 166, w: 288, h: 24, key: 'bar:wave:0', z: 7 })
  }

  // Positions differ in the dialog and the centered block, so each is its own page structure.
  const kind = s.dialog ? 'dialog' : s.center ? 'center' : s.alert ? 'alert' : blank ? 'blank' : 'plain'
  return { signature: `${kind}${s.bar ? '+bar' : ''}`, texts, images }
}
