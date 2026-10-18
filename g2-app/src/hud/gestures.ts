// Glasses gesture → POST /input. Only gestures the current screen offers are sent, with its screen_id.
// The engine answers by pushing the next hud.screen over SSE; nothing renders from the HTTP response.
//
// Tap-then-confirm (SPEC: "press, then a confirm screen"): on an approval screen (engine offers hold, not press)
// a tap shows a local confirm screen; a second tap sends `hold` for the original screen. Swipe = back.
// Long press still approves directly. The engine contract is unchanged: it only ever sees `hold`.
import { log } from '../debug/logger'
import type { Engine } from '../engine/client'
import type { Gesture } from '../engine/types'
import { currentGeneration, currentScreen, screenAgeMs, showScreen, showScreenIfCurrent } from './controller'
import { confirmScreen, gestureFailedScreen, type HudScreen } from './screens'

const FAILED_SCREEN_MS = 2500
const CONFIRM_TIMEOUT_MS = 6000 // an unanswered confirm goes back to the offer, so a stray later tap can't book

// Settle guard. Right after a page rebuild the simulator (and maybe the firmware) emits SCROLL events
// nobody made; one rejected the fee in testing. A swipe that early is never intentional, and a tap/hold
// within the first moment is usually a carry-over from the previous screen.
const SETTLE_MS: Record<Gesture, number> = { press: 300, hold: 300, swipe_down: 900 }
// The confirming tap must be a separate, deliberate tap (two fast taps are a double tap anyway).
const CONFIRM_SETTLE_MS = 500

let inFlight = false

function settled(screen: HudScreen, gesture: Gesture, minMs: number): boolean {
  const age = screenAgeMs()
  if (age >= minMs) return true
  log(`${gesture} ignored: ${screen.id} appeared ${Math.round(age)}ms ago`)
  return false
}

/** Entry point for every temple / mirror / keyboard gesture. */
export async function handleGesture(engine: Engine, gesture: Gesture): Promise<void> {
  const screen = currentScreen()

  // On the local confirm screen.
  if (screen.confirm) {
    const original = screen.confirm.of
    if (gesture === 'swipe_down') {
      if (settled(screen, gesture, SETTLE_MS.swipe_down)) {
        log('confirm cancelled, back to the offer')
        showScreen(original)
      }
      return
    }
    if (!settled(screen, gesture, gesture === 'press' ? CONFIRM_SETTLE_MS : SETTLE_MS.hold)) return
    log(`confirmed with ${gesture} → hold on ${original.id}`)
    return send(engine, 'hold', original)
  }

  // A tap on an approval screen opens the confirm step instead of being dropped.
  if (gesture === 'press' && screen.tapConfirms) {
    if (!settled(screen, gesture, SETTLE_MS.press)) return
    const gen = showScreen(confirmScreen(screen))
    setTimeout(() => {
      if (showScreenIfCurrent(gen, screen)) log('confirm timed out, back to the offer')
    }, CONFIRM_TIMEOUT_MS)
    return
  }

  if (!settled(screen, gesture, SETTLE_MS[gesture])) return
  return send(engine, gesture, screen)
}

/** POST /input for `screen` (the engine screen the gesture belongs to). */
async function send(engine: Engine, gesture: Gesture, screen: HudScreen): Promise<void> {
  if (!screen.gestures[gesture]) {
    log(`${gesture} does nothing on ${screen.id}; not sent`)
    return
  }
  if (inFlight) return // one request at a time: a double hold must not approve twice
  inFlight = true
  const gen = currentGeneration()
  try {
    const r = await engine.input(gesture, screen.id)
    if (!r.handled) log(`engine ignored ${gesture} (stage ${r.stage})`)
  } catch (err) {
    log(`POST /input ${gesture} failed: ${(err as Error).message}`)
    // Say so on the lens, then put the engine screen back so the wearer can retry.
    if (showScreenIfCurrent(gen, gestureFailedScreen())) {
      const failGen = currentGeneration()
      setTimeout(() => showScreenIfCurrent(failGen, screen), FAILED_SCREEN_MS)
    }
  } finally {
    inFlight = false
  }
}
