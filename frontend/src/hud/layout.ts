// Screen → page plan (where everything goes on the 576×288 lens).
// Single source of truth for BOTH the real glasses (bridge.ts) and the browser mirror (HudMirror.tsx).
//
// Budget: max 12 containers, 8 text, 4 image. This plan uses at most 5 text + 2 image.
// The structure only changes between "plain" / "alert" / "+bar" variants, so most screen changes are
// cheap textContainerUpgrade calls instead of full page rebuilds.
import type { HudScreen } from './screens'

export const LENS_W = 576
export const LENS_H = 288
export const BRIGHT = 4
export const DIM = 2
export const PADDING = 4
const MAX_CHARS = 40

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

export function planScreen(s: HudScreen): PagePlan {
  const texts: TextSpec[] = []
  if (s.alert) {
    texts.push({ id: 1, name: 'frame', x: 12, y: 80, w: 552, h: 120, color: DIM, content: BLANK, border: true, z: 1 })
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
      y: 156,
      w: 472,
      h: 40,
      color: DIM,
      content: (!s.bar && s.detail ? clamp(s.detail) : '') || BLANK,
      z: 4,
    },
    { id: 5, name: 'footer', x: 16, y: 236, w: 544, h: 44, color: DIM, content: clamp(s.footer ?? '') || BLANK, z: 5 },
  )

  const images: ImageSpec[] = [
    { id: 6, name: 'icon', x: 24, y: 96, w: 48, h: 48, key: `icon:${s.icon ?? 'none'}`, z: 6 },
  ]
  if (s.bar) {
    const key =
      s.bar.kind === 'wave' ? 'bar:wave' : `bar:progress:${Math.round(Math.min(1, Math.max(0, s.bar.value)) * 100)}`
    images.push({ id: 7, name: 'bar', x: 92, y: 166, w: 288, h: 24, key, z: 7 })
  }

  return { signature: `${s.alert ? 'alert' : 'plain'}${s.bar ? '+bar' : ''}`, texts, images }
}
