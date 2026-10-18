// Which screens animate, and how. Pure: the controller runs the timer.
//
// Rules (see design notes):
// - Only while the user waits: the call wave and the search spinner loop; the check draws in once.
// - Never on decision screens (approve / cancel alert), never blinking alerts, nothing on the clock.
// - 2–4 fps, few precomputed frames, small area (one 48×48 icon or the 288×24 bar).
// - Speed follows the image-update latency measured on the device; the spinner only runs when it's fast.
import { SPINNER_FRAME_COUNT, WAVE_FRAME_COUNT } from './images'
import type { HudScreen } from './screens'

export type Animation = {
  image: 'icon' | 'bar' | 'dot' // image container name in layout.ts
  frames: string[]
  restKey: string // static frame shown when the loop times out
  intervalMs: number
  loop: boolean
  maxMs: number // loops stop (and rest) after this
  optional: boolean // rest as soon as the link measures slow
}

/** Image updates slower than this mean the BLE link can't afford optional motion. */
export const SLOW_IMAGE_MS = 300
const LOOP_MAX_MS = 25_000

const range = (n: number, f: (i: number) => string) => Array.from({ length: n }, (_, i) => f(i))

/**
 * @param latencyMs average image update time; 0 in browser mode (mirror only), null if not measured yet.
 */
export function animationFor(s: HudScreen, latencyMs: number | null): Animation | null {
  const slow = latencyMs !== null && latencyMs > SLOW_IMAGE_MS

  // 0. Minimized call: a 12×12 dot blinking slowly next to the corner icon, so the call reads as live.
  //    Tiny image, ~1 update/s: runs for the whole call (calls outlast the 25 s loop cap), rests lit.
  if (s.mini) {
    return {
      image: 'dot',
      frames: ['dot:on', 'dot:off'],
      restKey: 'dot:on',
      intervalMs: slow ? 1000 : 700,
      loop: true,
      maxMs: 10 * 60_000,
      optional: false,
    }
  }

  // 1. Airline call: the demo's hero moment, and no decision is pending.
  if (s.bar?.kind === 'wave') {
    return {
      image: 'bar',
      frames: range(WAVE_FRAME_COUNT, (i) => `bar:wave:${i}`),
      restKey: 'bar:wave:0',
      intervalMs: slow ? 500 : 333,
      loop: true,
      maxMs: LOOP_MAX_MS,
      optional: false,
    }
  }

  // 2. Done: one-shot draw-in, then the complete check stays.
  if (s.icon === 'check') {
    return {
      image: 'icon',
      frames: ['icon:check:0', 'icon:check:1', 'icon:check'],
      restKey: 'icon:check',
      intervalMs: slow ? 300 : 180,
      loop: false,
      maxMs: 0,
      optional: false,
    }
  }

  // 3. Open-ended waits (searching): dot spinner in the icon slot, only on a fast link.
  //    Unmeasured counts as fast; the controller rests it as soon as a slow measurement arrives.
  //    Rest = the screen's own static icon (magnifier), never a frozen spinner that reads as "stuck".
  if (s.busy && !slow) {
    return {
      image: 'icon',
      frames: range(SPINNER_FRAME_COUNT, (i) => `icon:spinner:${i}`),
      restKey: `icon:${s.icon ?? 'none'}`,
      intervalMs: 300,
      loop: true,
      maxMs: LOOP_MAX_MS,
      optional: true,
    }
  }

  return null
}
