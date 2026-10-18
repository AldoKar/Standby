// Glasses gesture → POST /input. Only gestures the current screen offers are sent, with its screen_id.
// The engine answers by pushing the next hud.screen over SSE; nothing renders from the HTTP response.
//
// Tap-then-confirm (SPEC: "press, then a confirm screen"): on an approval screen (engine offers hold, not press)
// a tap shows a local confirm screen; a second tap sends `hold` for the original screen. Swipe = back.
// Long press still approves directly. The engine contract is unchanged: it only ever sees `hold`.
import { log } from '../debug/logger'
import type { Engine } from '../engine/client'
import type { Gesture } from '../engine/types'
import { isCallScreen, toggleCallView } from './callView'
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

// Push-to-talk (free mode) lives in the voice layer, which owns the mic; it registers itself here so this
// file doesn't import it (the voice layer already imports openConfirm from here).
type AskHandlers = { start: (engine: Engine) => void; cancel: () => void }
let askHandlers: AskHandlers | null = null
export function setAskHandlers(h: AskHandlers | null): void {
  askHandlers = h
}

/** Entry point for every temple / mirror / keyboard gesture. */
export async function handleGesture(engine: Engine, gesture: Gesture): Promise<void> {
  const screen = currentScreen()

  // On a push-to-talk step: tap/swipe = back, long press on "try again" = ask again.
  if (screen.ask) {
    if (!settled(screen, gesture, SETTLE_MS[gesture])) return
    if (gesture === 'hold' && screen.ask.phase === 'failed') askHandlers?.start(engine)
    else if (gesture !== 'hold') askHandlers?.cancel()
    return
  }

  // During a call, long press minimizes it to a corner icon / brings it back. Local only, never sent.
  if (gesture === 'hold' && (screen.mini || isCallScreen(screen))) {
    if (settled(screen, gesture, SETTLE_MS.hold)) toggleCallView()
    return
  }
  if (screen.mini) return // minimized: only the long press does something

  // Long press where the engine offers "ask" (free mode) = push-to-talk. Never sent to /input.
  if (gesture === 'hold' && screen.gestures.hold === 'ask') {
    if (!settled(screen, gesture, SETTLE_MS.hold)) return
    if (askHandlers) askHandlers.start(engine)
    else log('ask: voice layer not running')
    return
  }

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
    openConfirm(screen)
    return
  }

  if (!settled(screen, gesture, SETTLE_MS[gesture])) return
  return send(engine, gesture, screen)
}

/**
 * Show the local "Tap again to confirm" step for an approval screen. Used by the first tap and by a
 * voice "yes" on a spend (spends always need a tap). Times out back to the offer.
 */
export function openConfirm(screen: HudScreen): void {
  const original: HudScreen = { ...screen, voice: undefined }
  const gen = showScreen(confirmScreen(original))
  setTimeout(() => {
    if (showScreenIfCurrent(gen, original)) log('confirm timed out, back to the offer')
  }, CONFIRM_TIMEOUT_MS)
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
    if (!r.handled) log(`engine ignored ${gesture} (stage ${r.stage}${r.reason ? `: ${r.reason}` : ''})`)
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
