// DEV-only offline previews: the engine's demo screens (from engine/app/main.py and g2-app/README.md),
// published locally as hud.screen events. Used by the dev panel and `?shot=<screen_id>`.
// When ?shot is set the app doesn't connect to the engine, so the preview isn't overwritten.
import type { EngineScreen } from '../engine/types'

const s = (
  screen_id: string,
  lines: string[],
  gestures: EngineScreen['gestures'] = {},
  clear_after_s: number | null = null,
): EngineScreen => ({ screen_id, lines, gestures, clear_after_s })

export const SAMPLE_SCREENS: Record<string, EngineScreen> = {
  ready: s('ready', ['Ready', 'Tap = start, Hold = ask'], { press: 'start', hold: 'ask' }),
  answer: s('answer', ['UA1372 on time', 'Gate 85, Terminal 8', 'Departs 7:40 AM'], { press: 'dismiss', hold: 'ask' }, 10),
  cancelled: s('cancelled', ['UA183 cancelled', 'United: 7:05 AM tmrw', 'Tap = fix it'], { press: 'fix' }),
  booking_offer: s('booking_offer', ['Delta tonight 9:15 PM', '$215 · lands 10:40', 'Hold to book'], {
    hold: 'approve',
    swipe_down: 'other',
  }),
  only_option: s('only_option', ['Only option tonight', 'Delta 9:15 PM', 'Hold to book'], { hold: 'approve' }),
  booked: s('booked', ['Booked · pass saved']),
  calling: s('calling', ['Desk closes 11:00 PM', 'You land 10:40', 'Calling guesthouse']),
  fee_request: s('fee_request', ['+$40 late check-in', 'Guesthouse asks', 'Hold = OK, Swipe = no'], {
    hold: 'approve',
    swipe_down: 'reject',
  }),
  denied: s('denied', ['$90 late fee', 'Over your budget', 'Confirm on phone'], {}, 8),
  resolved: s('resolved', ['Room held', 'Door code 4417'], { press: 'dismiss' }, 10),
  idle: s('idle', []),
}

/** DEV-only lens screen to check which glyphs the font renders. */
// Known results (simulator 0.9.5): renders √ ★ ☎ → ● ○ · … ↑↓ ▁▃▅▇ — blank ✓ ✔ ☑ ✈ ⚠ ✕ — placeholder box ✅.
export const GLYPH_PROBE_LINES = ['A✓B A✔B A√B A☑B', 'A★B A✅B A✈B A⚠B', 'A☎B A→B A●B A✕B']
