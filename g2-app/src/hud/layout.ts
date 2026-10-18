// Screen → page plan (where everything goes on the 576×288 lens).
// Single source of truth for BOTH the real glasses (bridge.ts) and the browser mirror (HudMirror.tsx).
//
// Budget: max 12 containers, 8 text, 4 image. Worst case here is 6 text + 2 image
// (margin or alert frame, header, main, detail, footer/hint, voice tag + icon, bar).
// Choices render as ONE native hint line ("Tap = book  ·  Swipe ↓ = other"), left-aligned like Even's own
// apps, instead of fake buttons: no centring to fake, one read, and the page structure doesn't change between
// screens, so most transitions are cheap textContainerUpgrade calls instead of full rebuilds.
import { destinationArtKey, logoKey } from './images'
import { voiceTag, type HudChoice, type HudScreen } from './screens'

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

/** "Tap = book  ·  Swipe ↓ = other". Whether voice works here is the voice tag's job, not the hint's. */
export function hintText(choices: HudChoice[]): string {
  return choices.map((c) => `${GESTURE_WORD[c.gesture]} = ${c.label}`).join('  ·  ')
}

const headerText = (s: HudScreen) => s.header

// Voice tag: always the same place (top-right), so the wearer learns to glance there before speaking.
// Its own text container, always present (blank when there's nothing to say), so mic state changes are
// cheap text upgrades and never rebuild the page. Bright while the wearer is being heard.
const TAG = { x: 440, w: 124 }
const TAG_MAX_CHARS = 11
const HEADER_W = TAG.x - 16 - 8

function tagSpec(s: HudScreen, y: number): TextSpec {
  const text = voiceTag(s)
  const active = s.voice === 'hearing' || s.voice === 'thinking' || (s.ask?.phase === 'listening')
  return {
    id: 8,
    name: 'voice',
    x: TAG.x,
    y,
    w: TAG.w,
    h: 36,
    color: active ? BRIGHT : HINT,
    content: clamp(text, TAG_MAX_CHARS) || BLANK,
    z: 8,
  }
}

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
  // One instruction per line in the narrow box.
  const help = (s.choices ?? []).slice(0, 2).map((c) => `${GESTURE_WORD[c.gesture]} = ${c.label}`)
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
      tagSpec(s, 10), // inside the title box, right of the centred title
    ],
    images,
  }
}

// Call: the flight list's boxed layout (same title box, same section borders).
//   ┌──────────────── Calling guesthouse ───────── ○ Voice on ┐  title box, the title centred (image)
//   ├──────────────┬──────────────────────────────────────────┤
//   │              │ Desk closes 11:00 PM                     │  left: the phone, large
//   │     [☏]      │ You land 10:40                           │  right: the engine's lines (this box captures
//   │              │ ▮▯▮▮▯▮▯▮▮▯ (moving)                      │  gestures) and the voice wave under them
//   ├──────────────┴──────────────────────────────────────────┤
//   │ Hold = hide                                             │  footer box: the hint
//   └─────────────────────────────────────────────────────────┘
// 5 text (title box, phone box, text box, footer, voice tag) + 3 image (title, phone, wave).
const CALL_ICON_BOX = { x: 4, y: 56, w: 168, h: 172 }
const CALL_ICON = 96 // the 48×48 phone drawn at 2×
const CALL_TEXT_BOX = { x: 176, y: 56, w: 396, h: 172 }
const CALL_BAR = { w: 170, h: 32 } // 12 bars × 14 px
const CALL_FOOTER = { x: 4, y: 232, w: LENS_W - 8, h: 52 }

function planCall(s: HudScreen): PagePlan {
  const box = { border: true, borderLevel: SECTION_BORDER, radius: 8 }
  const images: ImageSpec[] = [
    {
      id: 7,
      name: 'icon',
      x: CALL_ICON_BOX.x + (CALL_ICON_BOX.w - CALL_ICON) / 2,
      y: CALL_ICON_BOX.y + (CALL_ICON_BOX.h - CALL_ICON) / 2,
      w: CALL_ICON,
      h: CALL_ICON,
      key: `icon:${s.icon ?? 'phone'}`,
      z: 7,
    },
  ]
  if (s.header) {
    images.unshift({ id: 6, name: 'title', x: (LENS_W - 288) / 2, y: 10, w: 288, h: 36, key: textImageKey(s.header, 22, 210), z: 6 })
  }
  if (s.bar) {
    // Under the two text lines (~28 px each, after the box padding), left-aligned with them.
    images.push({ id: 9, name: 'bar', x: CALL_TEXT_BOX.x + 14, y: CALL_TEXT_BOX.y + 96, ...CALL_BAR, key: 'bar:wave:0', z: 9 })
  }
  return {
    signature: `call${s.bar ? '+bar' : ''}`,
    texts: [
      { id: 1, name: 'titlebox', x: 4, y: 4, w: LENS_W - 8, h: 48, color: DIM, content: BLANK, ...box, z: 1 },
      { id: 2, name: 'iconbox', ...CALL_ICON_BOX, color: DIM, content: BLANK, ...box, z: 2 },
      {
        id: 3,
        name: 'main',
        ...CALL_TEXT_BOX,
        color: BRIGHT,
        content: s.lines.slice(0, 2).map((l) => clamp(l, 30)).join('\n') || BLANK,
        padding: 12,
        ...box,
        capture: true, // exactly one container captures gestures (long press = hide)
        z: 3,
      },
      {
        id: 5,
        name: 'footer',
        ...CALL_FOOTER,
        color: HINT,
        content: clamp(hintText(s.choices ?? []), HINT_MAX_CHARS) || BLANK,
        padding: 10,
        ...box,
        z: 5,
      },
      tagSpec(s, 10),
    ],
    images,
  }
}

// Home (`ready`): the logo centred, the line under it (drawn centred as an image: the SDK can't centre
// text), the gestures in the footer box like the call and the flight list. The footer box captures gestures.
//   ┌──────────────────────────────────────────────────────┐
//   │                     [  logo  ]                       │  no voice tag: the footer says it
//   │                     [        ]                       │  (Connecting… uses the same layout)
//   │            Ask Standby about your travel             │
//   ├──────────────────────────────────────────────────────┤
//   │ Tap = start  ·  Hold = ask                           │
//   └──────────────────────────────────────────────────────┘
// 2 text (footer, voice tag) + 2 image (logo, line).
const HOME_LOGO = { w: 152, h: 140, y: 14 } // public/standby-logo-g2.png is 152×140
const HOME_LINE_PX = 19 // what "Ask Standby about your travel" fits at in 288 px: "Connecting…" matches it, so nothing resizes
const HOME_LINE_BOX = { w: 288, h: 36, y: 182 } // 288 = the widest image the glasses take; the text shrinks to fit

function planHome(s: HudScreen): PagePlan {
  const box = { border: true, borderLevel: SECTION_BORDER, radius: 8 }
  return {
    signature: 'home',
    texts: [
      {
        id: 5,
        name: 'footer',
        ...CALL_FOOTER,
        // The gestures; on Connecting… the build stamp, dim.
        color: s.choices?.length ? HINT : DIM,
        content: (s.choices?.length ? clamp(hintText(s.choices), HINT_MAX_CHARS) : clamp(s.footer ?? '')) || BLANK,
        padding: 10,
        ...box,
        capture: true, // exactly one container captures gestures
        z: 5,
      },
      tagSpec(s, 10),
    ],
    images: [
      { id: 6, name: 'logo', x: (LENS_W - HOME_LOGO.w) / 2, y: HOME_LOGO.y, w: HOME_LOGO.w, h: HOME_LOGO.h, key: logoKey(), z: 6 },
      {
        id: 7,
        name: 'line',
        x: (LENS_W - HOME_LINE_BOX.w) / 2,
        y: HOME_LINE_BOX.y,
        w: HOME_LINE_BOX.w,
        h: HOME_LINE_BOX.h,
        key: textImageKey(s.lines[0] ?? '', HOME_LINE_PX, 230),
        z: 7,
      },
    ],
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
  if (s.call) return planCall(s)
  if (s.home) return planHome(s)
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
      w: HEADER_W,
      h: 44,
      color: DIM,
      content: clamp(headerText(s), 32) || BLANK,
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
      content: (hasHint ? clamp(hintText(s.choices ?? []), HINT_MAX_CHARS) : clamp(s.footer ?? '')) || BLANK,
      z: 5,
    },
    tagSpec(s, 12),
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
