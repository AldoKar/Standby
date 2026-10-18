// Minimized call (app-owned presentation; the engine never knows).
//
// Some wearers don't want the call on the lens the whole time: a long press on a call screen shrinks it to a
// small phone icon in the corner, and another long press brings it back. The choice lasts for the whole call:
// - calling → call_resumed stays minimized,
// - a screen that needs the wearer (the fee mid-call) always shows in full, then the call goes back to the icon,
// - anything else (the outcome, ready…) ends the call view and clears the choice.
import { log } from '../debug/logger'
import { currentScreen, showScreen } from './controller'
import type { HudScreen } from './screens'

const CALL_SCREENS = new Set(['calling', 'call_resumed'])
// Shown in full mid-call without ending the minimized choice (the call goes on behind them).
const DURING_CALL = new Set(['fee_request', 'denied'])

let minimized = false

export const isCallScreen = (s: HudScreen) => CALL_SCREENS.has(s.id)

export function minimizedScreen(of: HudScreen): HudScreen {
  // The call screen comes back without a stale voice state ("Heard you" from the "hide it" that minimized it).
  return { id: `mini:${of.id}`, header: '', lines: [], icon: 'phone', gestures: {}, mini: { of: { ...of, voice: undefined } } }
}

/** Every engine hud.screen goes through here, so a minimized call stays minimized. */
export function presentEngineScreen(s: HudScreen, clearAfterS: number | null): void {
  if (isCallScreen(s)) {
    showScreen(minimized ? minimizedScreen(s) : s, clearAfterS)
    return
  }
  if (minimized && !DURING_CALL.has(s.id)) {
    log('call view: call over, minimized choice cleared')
    minimized = false
  }
  showScreen(s, clearAfterS)
}

/** Long press: minimize / restore the call. Returns false if this isn't a call screen (gesture goes on). */
export function toggleCallView(): boolean {
  const s = currentScreen()
  if (s.mini) {
    minimized = false
    log('call view: restored')
    showScreen(s.mini.of)
    return true
  }
  if (isCallScreen(s)) {
    minimized = true
    log('call view: minimized')
    showScreen(minimizedScreen(s))
    return true
  }
  return false
}
