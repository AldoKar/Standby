// Screen → page plan (where everything goes on the 576×288 lens).
// Single source of truth for BOTH the real glasses (bridge.ts) and the browser mirror (HudMirror.tsx).
//
// Budget: max 12 containers, 8 text, 4 image. Worst case here (alert + two choices) is exactly 8 text + 1 image:
// frame, header, main, detail, 2 buttons, 2 gesture captions. Don't add a text container without removing one.
// The structure only changes between plain/alert, +bar and choice-count variants, so most screen changes are
// cheap textContainerUpgrade calls instead of full page rebuilds.
import type { HudScreen } from './screens'

export const LENS_W = 576
export const LENS_H = 288
export const BRIGHT = 4
export const DIM = 2
export const PADDING = 4
const MAX_CHARS = 40

// Approximate glyph advance of the lens font (single size). Measured on simulator screenshots: ~9.5 px/char.
// Used to hug buttons around their label and centre the gesture caption below. Re-check on real G2.
const CHAR_W = 10
// Same padding as other single-line containers: more vertical padding overflows the line and the
// firmware/simulator draws a scroll indicator inside the button.
const BUTTON_PAD = PADDING
const BUTTON_MIN_W = 96
const BUTTON_SIDE = 14 // extra room per side, so wide glyphs (A, p, v) don't touch the border
const BUTTON_GAP = 20

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
  radius?: number
  padding?: number
  capture?: boolean
  z: number
}

export type ImageSpec = { id: number; name: string; x: number; y: number; w: number; h: number; key: string; z: number }

export type PagePlan = { signature: string; texts: TextSpec[]; images: ImageSpec[] }

// The host may reject empty text containers, so blanks are a single space.
const BLANK = ' '

function clamp(line: string): string {
  return line.length > MAX_CHARS ? `${line.slice(0, MAX_CHARS - 1)}…` : line
}

const textWidth = (s: string) => s.length * CHAR_W

/** Bordered "buttons" with their gesture underneath, left-aligned in the footer zone. */
function choiceButtons(choices: NonNullable<HudScreen['choices']>): TextSpec[] {
  const items = [
    { label: choices.tap, gesture: 'tap' },
    ...(choices.hold ? [{ label: choices.hold, gesture: 'hold' }] : []),
  ]
  const out: TextSpec[] = []
  let x = 16
  items.forEach((item, k) => {
    const label = item.label.slice(0, 12)
    const w = Math.max(BUTTON_MIN_W, textWidth(label) + BUTTON_PAD * 2 + BUTTON_SIDE * 2)
    // Pad the label with leading spaces so it sits roughly centred (the SDK has no text alignment).
    const spare = w - BUTTON_PAD * 2 - textWidth(label)
    const lead = ' '.repeat(Math.max(0, Math.round(spare / 2 / (CHAR_W * 0.55))))
    out.push({
      id: 8 + k,
      name: `btn-${item.gesture}`,
      x,
      y: 198,
      w,
      h: 40,
      color: BRIGHT,
      content: lead + label,
      border: true,
      radius: 6,
      padding: BUTTON_PAD,
      z: 8 + k,
    })
    const capW = textWidth(item.gesture) + PADDING * 2 + 4
    out.push({
      id: 10 + k,
      name: `cap-${item.gesture}`,
      x: x + Math.round((w - capW) / 2),
      y: 240,
      w: capW,
      h: 40,
      color: DIM,
      content: item.gesture,
      z: 10 + k,
    })
    x += w + BUTTON_GAP
  })
  return out
}

export function planScreen(s: HudScreen): PagePlan {
  const texts: TextSpec[] = []
  if (s.alert) {
    texts.push({ id: 1, name: 'frame', x: 12, y: 80, w: 552, h: 110, color: DIM, content: BLANK, border: true, z: 1 })
  }
  texts.push(
    { id: 2, name: 'header', x: 16, y: 12, w: 544, h: 44, color: DIM, content: clamp(s.header) || BLANK, z: 2 },
    {
      id: 3,
      name: 'main',
      x: 84,
      y: 86,
      w: 472,
      h: 72,
      color: BRIGHT,
      content: s.lines.slice(0, 2).map(clamp).join('\n') || BLANK,
      capture: true, // exactly one container captures gestures
      z: 3,
    },
    {
      id: 4,
      name: 'detail',
      x: 84,
      y: 152,
      w: 472,
      h: 40,
      color: DIM,
      content: (!s.bar && s.detail ? clamp(s.detail) : '') || BLANK,
      z: 4,
    },
  )
  if (s.choices) {
    texts.push(...choiceButtons(s.choices))
  } else {
    texts.push({ id: 5, name: 'footer', x: 16, y: 236, w: 544, h: 44, color: DIM, content: clamp(s.footer ?? '') || BLANK, z: 5 })
  }

  const images: ImageSpec[] = [
    { id: 6, name: 'icon', x: 24, y: 96, w: 48, h: 48, key: `icon:${s.icon ?? 'none'}`, z: 6 },
  ]
  if (s.bar) {
    images.push({ id: 7, name: 'bar', x: 92, y: 166, w: 288, h: 24, key: 'bar:wave:0', z: 7 })
  }

  const choiceCount = s.choices ? (s.choices.hold ? 2 : 1) : 0
  return {
    signature: `${s.alert ? 'alert' : 'plain'}${s.bar ? '+bar' : ''}${choiceCount ? `+choices${choiceCount}` : ''}`,
    texts,
    images,
  }
}
