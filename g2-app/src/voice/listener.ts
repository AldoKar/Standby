// Voice on the glasses mic. Two uses, one mic:
//
// 1. Commands: utterance → POST /voice → same flow as a gesture.
//    - The mic is open only on screens that take voice commands (VOICE_SCREENS), and stays open through the
//      local confirm step so swiping back doesn't toggle it. Closed everywhere else, and on foreground exit.
//    - A spend approval by voice never goes to the engine: it opens "Tap again to confirm" (product rule).
// 2. Free questions (free mode, before Start): push-to-talk. A long press where the engine offers
//    `hold: "ask"` opens the mic for ONE question (any language) → POST /ask → the engine pushes the
//    `answer` screen. Never always-on: nearby talk must not trigger questions.
//
// - "Live" means audio chunks actually arrived; the audioControl boolean can lie in QR sideload.
// - The voice tag (top-right, hud/screens.ts voiceTag) shows the mic state BEFORE the wearer speaks:
//   "○ Voice on" as soon as a voice screen shows, "● Listening" the moment speech starts, "● Heard you"
//   while it's being understood, "Voice off" if no audio arrives. Tap-only screens say "Tap only".
// - One request in flight at a time; every result is gated by the screen generation, so a late answer
//   never touches a newer screen.
// - Taps keep working the whole time; voice is an extra path, never a trap.
import { log } from '../debug/logger'
import { HttpError, type Engine } from '../engine/client'
import type { VoiceResult } from '../engine/types'
import { canUseMic, onAudio, setMic } from '../glasses/bridge'
import { currentGeneration, currentScreen, onScreenChange, patchScreen, showScreen, showScreenIfCurrent } from '../hud/controller'
import { chooseRow, openConfirm, setAskHandlers } from '../hud/gestures'
import { toggleCallView } from '../hud/callView'
import { askScreen, engineScreenId, takesVoice, type HudScreen, type VoiceState } from '../hud/screens'
import { UtteranceDetector, wavBase64, type Utterance } from './detector'

const VERIFY_MS = 2000 // audio chunks should arrive this soon after opening the mic
const FLASH_MS = 2500 // how long "didn't catch that" / "voice off" stays in the header
const HANDLED_FALLBACK_MS = 4000 // if the engine handled it but no new screen came, drop "heard you"

const ASK_NO_SPEECH_MS = 7000 // push-to-talk with no question → back
const ASK_FAILED_MS = 2500 // how long a failure stays before going back
const ASK_ANSWER_WAIT_MS = 4000 // /ask returned but the answer screen didn't arrive over SSE → back
const ASK_TIMING = { endSilenceMs: 1200, maxMs: 10000 } // questions are longer and have pauses

let live = false // real audio has arrived since the mic was opened
let micDead = false // the mic was opened but no audio arrived: the tag says "Voice off"
let inFlight = false

/** Mic state when nothing is happening: waiting for speech, or off if the mic never delivered audio. */
const idleState = (): VoiceState => (micDead ? 'offline' : 'listening')

function setVoice(gen: number, voice: VoiceState | undefined) {
  if (currentScreen().voice !== voice) patchScreen(gen, { voice })
}

function flash(gen: number, state: VoiceState) {
  setVoice(gen, state)
  setTimeout(() => setVoice(gen, idleState()), FLASH_MS)
}

// ---------- commands (POST /voice) ----------

/** Apply a /voice answer to the screen it was spoken on (shared by the mic and the typed tester). */
function applyResult(engine: Engine, r: VoiceResult, screen: HudScreen, gen: number, ms: number) {
  log(
    `voice ${ms}ms: "${r.transcript}" → ${r.intent} (${r.via}, ${r.confidence.toFixed(2)})` +
      `${r.index !== undefined && r.index !== null ? ` row ${r.index}` : ''}${r.model ? ` [${r.model}]` : ''}` +
      `${r.handled ? ' handled' : ''}${r.confirm_required ? ' → tap to confirm' : ''}${r.reason ? ` · ${r.reason}` : ''}`,
  )
  if (gen !== currentGeneration()) return // a newer screen is showing; the engine already moved on
  if (r.reason === 'local' && (r.intent === 'hide' || r.intent === 'show')) {
    // The call view is the glasses' own: "hide it" minimizes, "show it" restores (no-op if already so).
    if ((r.intent === 'hide') !== Boolean(screen.mini)) toggleCallView()
    return
  }
  if (r.confirm_required && r.intent === 'choose' && screen.list && typeof r.index === 'number') {
    chooseRow(engine, r.index) // "the Alaska one": select it, then "Confirm with a tap" naming it
  } else if (r.confirm_required) {
    openConfirm(screen)
  } else if (r.handled) {
    setTimeout(() => setVoice(gen, idleState()), HANDLED_FALLBACK_MS)
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
    const r = await engine.voice({ screen_id: engineScreenId(screen), format: 'wav', ...body })
    applyResult(engine, r, screen, gen, Math.round(performance.now() - startedAt))
  } catch (err) {
    log(`POST /voice failed: ${(err as Error).message}`)
    if (gen === currentGeneration()) flash(gen, 'offline')
  } finally {
    inFlight = false
  }
}

// ---------- free questions (POST /ask, push-to-talk) ----------

let askTimer: ReturnType<typeof setTimeout> | null = null
// Set while startVoice runs: opens/closes the mic for one question.
let askMic: ((on: boolean) => void) | null = null

function clearAskTimer() {
  if (askTimer) clearTimeout(askTimer)
  askTimer = null
}

/** The engine screen behind the current one (a push-to-talk step goes back to it). */
function askOrigin(): HudScreen {
  const s = currentScreen()
  return s.ask ? s.ask.of : { ...s, voice: undefined }
}

const freeMode = (s: HudScreen) => s.gestures.hold === 'ask' || Boolean(s.ask)

function askFailed(of: HudScreen, why: string) {
  clearAskTimer()
  const gen = showScreen(askScreen(of, 'failed', why))
  askTimer = setTimeout(() => showScreenIfCurrent(gen, of), ASK_FAILED_MS)
}

function failureText(err: unknown): string {
  if (err instanceof HttpError) {
    if (err.status === 422) return "Didn't catch that"
    if (err.status === 503) return 'Questions are off'
    if (err.status === 413) return 'Too long, try again'
  }
  return "Couldn't answer"
}

/** Long press in free mode: open the mic for one question. */
function beginAsk(engine: Engine) {
  if (inFlight) return
  const of = askOrigin()
  clearAskTimer()
  if (!askMic) {
    log('ask: no glasses mic here; type the question in the voice tester')
    askFailed(of, 'Mic off · type it on the page')
    return
  }
  askEngine = engine
  const gen = showScreen(askScreen(of, 'listening'))
  askMic(true)
  askTimer = setTimeout(() => {
    if (gen !== currentGeneration()) return
    log('ask: no question heard')
    askMic?.(false)
    askFailed(of, "Didn't hear a question")
  }, ASK_NO_SPEECH_MS)
}
let askEngine: Engine | null = null

/** Tap on a push-to-talk step: back to where the wearer was. */
function cancelAsk() {
  clearAskTimer()
  askMic?.(false)
  const s = currentScreen()
  if (s.ask) {
    log('ask: cancelled')
    showScreen(s.ask.of)
  }
}

async function submitAsk(engine: Engine, body: { audio?: string; question?: string }, startedAt: number) {
  if (inFlight) return
  const of = askOrigin()
  clearAskTimer()
  askMic?.(false)
  inFlight = true
  const gen = showScreen(askScreen(of, 'thinking'))
  try {
    const r = await engine.ask({ format: 'wav', ...body })
    log(
      `ask ${Math.round(performance.now() - startedAt)}ms: "${r.question}" → ${r.glasses.join(' / ')}` +
        `${r.shown ? '' : ' (not shown: a spend is waiting)'}`,
    )
    // The answer screen comes over SSE (usually before this response). If it doesn't, go back.
    if (gen === currentGeneration()) askTimer = setTimeout(() => showScreenIfCurrent(gen, of), r.shown ? ASK_ANSWER_WAIT_MS : 0)
  } catch (err) {
    log(`POST /ask failed: ${(err as Error).message}`)
    if (gen === currentGeneration()) askFailed(of, failureText(err))
  } finally {
    inFlight = false
  }
}

setAskHandlers({ start: beginAsk, cancel: cancelAsk })

/** Typed text (developer tools / browser without a mic): a question in free mode, else a command. */
export function sayText(engine: Engine, text: string): void {
  if (freeMode(currentScreen())) {
    void submitAsk(engine, { question: text }, performance.now())
    return
  }
  if (!takesVoice(currentScreen())) {
    log(`voice: no commands on ${currentScreen().id}`)
    return
  }
  void send(engine, { transcript: text }, performance.now())
}

// ---------- the mic ----------

/**
 * Real glasses always run inside the Even app on a phone. On a desktop (the simulator) "the glasses mic"
 * is the laptop's, which hears the whole room: never open it there. `?mic=on` forces it for testing.
 */
export function micAllowed(): boolean {
  if (new URLSearchParams(location.search).get('mic') === 'on') return true
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
}

/** Start listening on the glasses mic. Call once the bridge is connected. Returns a stop function. */
export function startVoice(engine: Engine): () => void {
  if (!canUseMic()) {
    log('voice: no glasses bridge, mic disabled (typed commands still work)')
    return () => {}
  }
  if (!micAllowed()) {
    log('voice: desktop (simulator), the laptop mic stays off; type commands in the voice tester (?mic=on forces it)')
    return () => {}
  }
  let wantMic = false
  let chunks = 0
  let verifyTimer: ReturnType<typeof setTimeout> | null = null
  let asking = false // the mic is open for one free question

  const detector = new UtteranceDetector(
    (u: Utterance) => {
      log(`voice: utterance ${u.ms}ms`)
      void send(engine, { audio: wavBase64(u.pcm) }, u.endedAt)
    },
    () => {
      log('voice: speech started')
      // Show it while they talk, not after: the wearer sees they're being heard.
      if (takesVoice(currentScreen()) && !inFlight) setVoice(currentGeneration(), 'hearing')
    },
    {},
    () => {
      // Too short to be a command (a cough, a click): back to waiting.
      if (currentScreen().voice === 'hearing') setVoice(currentGeneration(), idleState())
    },
  )

  const askDetector = new UtteranceDetector(
    (u: Utterance) => {
      if (!asking || currentScreen().ask?.phase !== 'listening') return
      log(`ask: question ${u.ms}ms`)
      void submitAsk(askEngine ?? engine, { audio: wavBase64(u.pcm) }, u.endedAt)
    },
    () => {
      log('ask: speech started')
      // They're talking: no "didn't hear a question". A cough the detector drops ends no utterance,
      // so keep a backstop past the longest question.
      clearAskTimer()
      const gen = currentGeneration()
      const of = askOrigin()
      askTimer = setTimeout(() => {
        if (gen !== currentGeneration()) return
        askMic?.(false)
        askFailed(of, "Didn't catch that")
      }, ASK_TIMING.maxMs + 2000)
    },
    ASK_TIMING,
  )

  async function open() {
    wantMic = true
    live = false
    micDead = false
    chunks = 0
    detector.reset()
    // Say "Voice on" right away; waiting for the first audio chunk made it look like voice wasn't there.
    if (takesVoice(currentScreen())) setVoice(currentGeneration(), 'listening')
    const said = await setMic(true)
    if (verifyTimer) clearTimeout(verifyTimer)
    verifyTimer = setTimeout(() => {
      if (wantMic && chunks === 0) {
        log(`voice: no audio ${VERIFY_MS}ms after opening the mic (audioControl said ${said})`)
        micDead = true
        if (takesVoice(currentScreen())) setVoice(currentGeneration(), 'offline')
      }
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

  askMic = (on: boolean) => {
    asking = on
    askDetector.reset()
    if (on) {
      if (!wantMic) void open()
    } else if (!takesVoice(currentScreen())) {
      close()
    }
  }

  const offAudio = onAudio((pcm, role) => {
    if (!wantMic) return
    chunks++
    if (!live) {
      live = true
      log('voice: mic live')
      if (micDead) {
        micDead = false // late audio: the mic works after all
        if (takesVoice(currentScreen())) setVoice(currentGeneration(), 'listening')
      }
    }
    if (asking) askDetector.push(pcm, role)
    else if (takesVoice(currentScreen()) && !inFlight) detector.push(pcm, role)
  })

  const offScreen = onScreenChange((screen, gen) => {
    detector.reset() // never carry half a phrase from one screen to the next
    if (screen.ask) return // push-to-talk manages the mic itself
    if (asking) {
      // An engine screen replaced the push-to-talk step (e.g. the answer): the question is over.
      asking = false
      askDetector.reset()
    }
    if (takesVoice(screen)) {
      if (!wantMic) void open()
      else setVoice(gen, idleState())
    } else if (!screen.confirm) {
      close() // keep the mic through the confirm step; close it everywhere else
    }
  })

  // The app may start on a voice screen (e.g. reconnecting mid-flow).
  if (takesVoice(currentScreen())) void open()

  return () => {
    askMic = null
    offAudio()
    offScreen()
    close()
  }
}
