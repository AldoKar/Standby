// Voice commands: glasses mic → utterance → POST /voice → same flow as a gesture.
//
// - The mic is open only on screens that take voice commands (VOICE_SCREENS), and stays open through the
//   local confirm step so swiping back doesn't toggle it. Closed everywhere else, and on foreground exit.
// - "Live" means audio chunks actually arrived; the audioControl boolean can lie in QR sideload.
// - One utterance in flight at a time; every result is gated by the screen generation, so a late answer
//   never touches a newer screen.
// - A spend approval by voice never goes to the engine: it opens "Tap again to confirm" (product rule).
// - Taps keep working the whole time; voice is an extra path, never a trap.
import { log } from '../debug/logger'
import type { Engine } from '../engine/client'
import type { VoiceResult } from '../engine/types'
import { canUseMic, onAudio, setMic } from '../glasses/bridge'
import { currentGeneration, currentScreen, onScreenChange, patchScreen } from '../hud/controller'
import { openConfirm } from '../hud/gestures'
import { VOICE_SCREENS, type HudScreen, type VoiceState } from '../hud/screens'
import { UtteranceDetector, wavBase64, type Utterance } from './detector'

const VERIFY_MS = 2000 // audio chunks should arrive this soon after opening the mic
const FLASH_MS = 2500 // how long "didn't catch that" / "voice off" stays in the header
const HANDLED_FALLBACK_MS = 4000 // if the engine handled it but no new screen came, drop "heard you"

let live = false // real audio has arrived since the mic was opened
let inFlight = false

const takesVoice = (s: HudScreen) => VOICE_SCREENS.has(s.id) && !s.confirm

function setVoice(gen: number, voice: VoiceState | undefined) {
  if (currentScreen().voice !== voice) patchScreen(gen, { voice })
}

function flash(gen: number, state: VoiceState) {
  setVoice(gen, state)
  setTimeout(() => setVoice(gen, live ? 'listening' : undefined), FLASH_MS)
}

/** Apply a /voice answer to the screen it was spoken on (shared by the mic and the typed tester). */
function applyResult(r: VoiceResult, screen: HudScreen, gen: number, ms: number) {
  log(
    `voice ${ms}ms: "${r.transcript}" → ${r.intent} (${r.via}, ${r.confidence.toFixed(2)})` +
      `${r.handled ? ' handled' : ''}${r.confirm_required ? ' → tap to confirm' : ''}${r.reason ? ` · ${r.reason}` : ''}`,
  )
  if (gen !== currentGeneration()) return // a newer screen is showing; the engine already moved on
  if (r.confirm_required) {
    openConfirm(screen)
  } else if (r.handled) {
    setTimeout(() => setVoice(gen, live ? 'listening' : undefined), HANDLED_FALLBACK_MS)
  } else if (r.reason?.startsWith('stale screen')) {
    // the next hud.screen is on its way
  } else if (r.reason && /not configured|transcription failed|intent model failed/.test(r.reason)) {
    flash(gen, 'offline')
  } else {
    flash(gen, 'missed')
  }
}

async function send(engine: Engine, body: { audio?: string; transcript?: string }, startedAt: number) {
  const screen = currentScreen()
  const gen = currentGeneration()
  if (!takesVoice(screen) || inFlight) return
  inFlight = true
  setVoice(gen, 'thinking')
  try {
    const r = await engine.voice({ screen_id: screen.id, format: 'wav', ...body })
    applyResult(r, screen, gen, Math.round(performance.now() - startedAt))
  } catch (err) {
    log(`POST /voice failed: ${(err as Error).message}`)
    if (gen === currentGeneration()) flash(gen, 'offline')
  } finally {
    inFlight = false
  }
}

/** Typed command for the current screen (developer tools / browser without a mic). */
export function sayText(engine: Engine, text: string): void {
  if (!takesVoice(currentScreen())) {
    log(`voice: no commands on ${currentScreen().id}`)
    return
  }
  void send(engine, { transcript: text }, performance.now())
}

/** Start listening on the glasses mic. Call once the bridge is connected. Returns a stop function. */
export function startVoice(engine: Engine): () => void {
  if (!canUseMic()) {
    log('voice: no glasses bridge, mic disabled (typed commands still work)')
    return () => {}
  }
  let wantMic = false
  let chunks = 0
  let verifyTimer: ReturnType<typeof setTimeout> | null = null

  const detector = new UtteranceDetector(
    (u: Utterance) => {
      log(`voice: utterance ${u.ms}ms`)
      void send(engine, { audio: wavBase64(u.pcm) }, u.endedAt)
    },
    () => log('voice: speech started'),
  )

  async function open() {
    wantMic = true
    live = false
    chunks = 0
    detector.reset()
    const said = await setMic(true)
    if (verifyTimer) clearTimeout(verifyTimer)
    verifyTimer = setTimeout(() => {
      if (wantMic && chunks === 0) log(`voice: no audio ${VERIFY_MS}ms after opening the mic (audioControl said ${said})`)
    }, VERIFY_MS)
  }

  function close() {
    if (!wantMic) return
    wantMic = false
    live = false
    detector.reset()
    if (verifyTimer) clearTimeout(verifyTimer)
    void setMic(false)
  }

  const offAudio = onAudio((pcm, role) => {
    if (!wantMic) return
    chunks++
    if (!live) {
      live = true
      log('voice: mic live')
      if (takesVoice(currentScreen())) setVoice(currentGeneration(), 'listening')
    }
    if (takesVoice(currentScreen()) && !inFlight) detector.push(pcm, role)
  })

  const offScreen = onScreenChange((screen, gen) => {
    detector.reset() // never carry half a phrase from one screen to the next
    if (takesVoice(screen)) {
      if (!wantMic) void open()
      else if (live) setVoice(gen, 'listening')
    } else if (!screen.confirm) {
      close() // keep the mic through the confirm step; close it everywhere else
    }
  })

  // The app may start on a voice screen (e.g. reconnecting mid-flow).
  if (takesVoice(currentScreen())) void open()

  return () => {
    offAudio()
    offScreen()
    close()
  }
}
