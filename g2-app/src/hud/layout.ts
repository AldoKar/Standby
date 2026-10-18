// Screen → page plan (where everything goes on the 576×288 lens).
// Single source of truth for BOTH the real glasses (bridge.ts) and the browser mirror (HudMirror.tsx).
//
// Budget: max 12 containers, 8 text, 4 image. Worst case here is 5 text + 2 image
// (margin or alert frame, header, main, detail, footer/hint + icon, bar).
// Choices render as ONE native hint line ("Tap = book  ·  Swipe ↓ = other"), left-aligned like Even's own
// apps, instead of fake buttons: no centring to fake, one read, and the page structure doesn't change between
// screens, so most transitions are cheap textContainerUpgrade calls instead of full rebuilds.
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

export type PagePlan = { signature: string; texts: TextSpec[]; images: ImageSpec[] }

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
  thinking: 'STANDBY · HEARD YOU…',
  missed: "STANDBY · DIDN'T CATCH THAT",
  offline: 'STANDBY · VOICE OFF',
}

// App margin: a thin, low-brightness outline around the whole app area, so the wearer always knows where
// Standby's space ends and the world begins. Not on alerts (their bright card stands alone) and not on a
// blank lens (quiet by default). Fixed geometry: it never forces a page rebuild between normal screens.
const MARGIN = { x: 4, y: 4, w: LENS_W - 8, h: LENS_H - 8, level: 5, radius: 12 }

export function planScreen(s: HudScreen): PagePlan {
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
      content: clamp((s.voice && VOICE_HEADER[s.voice]) || s.header) || BLANK,
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
