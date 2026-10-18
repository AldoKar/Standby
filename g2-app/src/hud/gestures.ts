// Glasses gesture → POST /input. Only gestures the current screen offers are sent, with its screen_id.
// The engine answers by pushing the next hud.screen over SSE; nothing renders from the HTTP response.
import { log } from '../debug/logger'
import type { Engine } from '../engine/client'
import type { Gesture } from '../engine/types'
import { currentGeneration, currentScreen, screenAgeMs, showScreenIfCurrent } from './controller'
import { gestureFailedScreen } from './screens'

const FAILED_SCREEN_MS = 2500

// Settle guard. Right after a page rebuild the simulator (and maybe the firmware) emits SCROLL events
// nobody made; one rejected the fee in testing. A swipe that early is never intentional, and a tap/hold
// within the first moment is usually a carry-over from the previous screen.
const SETTLE_MS: Record<Gesture, number> = { press: 300, hold: 300, swipe_down: 900 }

let inFlight = false

export async function sendGesture(engine: Engine, gesture: Gesture): Promise<void> {
  const screen = currentScreen()
  if (!screen.gestures[gesture]) {
    log(`${gesture} does nothing on ${screen.id}; not sent`)
    return
  }
  const age = screenAgeMs()
  if (age < SETTLE_MS[gesture]) {
    log(`${gesture} ignored: ${screen.id} appeared ${Math.round(age)}ms ago`)
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
    // Say so on the lens, then put the same screen back so the wearer can retry the gesture.
    if (showScreenIfCurrent(gen, gestureFailedScreen())) {
      const failGen = currentGeneration()
      setTimeout(() => showScreenIfCurrent(failGen, screen), FAILED_SCREEN_MS)
    }
  } finally {
    inFlight = false
  }
}
