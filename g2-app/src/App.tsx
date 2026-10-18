import { useEffect, useMemo, useState } from 'react'
import './App.css'
import { eventToChat } from './chat/eventText'
import { ChatPanel, type ChatMessage } from './components/ChatPanel'
import { DebugLog } from './components/DebugLog'
import { FlowSteps, type Step } from './components/FlowSteps'
import { HudMirror } from './components/HudMirror'
import { log } from './debug/logger'
import { DevPanel } from './dev/DevPanel'
import { GLYPH_PROBE_LINES, SAMPLE_SCREENS } from './dev/sampleScreens'
import { connectEngine, createEngine, engineUrl, type EngineStatus } from './engine/client'
import type { EngineEvent, Gesture } from './engine/types'
import { publish, subscribe } from './events/bus'
import { emitInput, initGlasses, onGlassesInput, type BridgeStatus, type GlassesInput } from './glasses/bridge'
import { currentPagePlan, currentScreen, showScreen, subscribeHud } from './hud/controller'
import { handleGesture } from './hud/gestures'
import { planScreen } from './hud/layout'
import { fromEngine, idleScreen, offlineScreen, type HudScreen } from './hud/screens'
import { startVoice } from './voice/listener'
import { VoiceTester } from './voice/VoiceTester'

const BUILD = `build ${__BUILD_ID__}`
const HELP = 'The trip chat lives in ASI:One. Here you can type "simulate" to start the demo or "reset".'

const params = new URLSearchParams(location.search)
// `?dev` opens the developer tools (also reachable from the footer toggle).
const DEV_OPEN = params.has('dev')
// DEV-only `?shot=<screen_id>|glyphs` previews one screen offline (no engine connection) for simulator captures.
const SHOT = import.meta.env.DEV ? params.get('shot') : null
const INITIAL: HudScreen =
  SHOT === 'glyphs'
    ? { id: 'glyphs', header: 'GLYPH PROBE', lines: GLYPH_PROBE_LINES.slice(0, 2), detail: GLYPH_PROBE_LINES[2], gestures: {} }
    : SHOT && SAMPLE_SCREENS[SHOT]
      ? fromEngine(SAMPLE_SCREENS[SHOT])
      : idleScreen(BUILD)

// Once at module load, not in an effect: StrictMode re-runs effects and would overwrite newer screens.
showScreen(INITIAL)
let nextMsgId = 1

const welcome = (): ChatMessage => ({ id: nextMsgId++, role: 'agent', text: "Hi, I'm Standby. I'm watching your trip." })

/** Which demo step an event belongs to (drives the highlighted step). Null = keep the current one. */
function stepFor(e: EngineEvent): Step | null | 'reset' {
  switch (e.type) {
    case 'flight.cancelled':
    case 'options.ranked':
      return 1
    case 'approval.requested':
      return e.data.kind === 'booking' ? 2 : 3
    case 'offer.declined':
      return 2
    case 'cutoff.detected':
    case 'call.started':
      return 3
    case 'task.resolved':
      return 4
    case 'demo.reset':
      return 'reset'
    case 'hud.screen':
      return e.data.screen_id === 'ready' ? 'reset' : null
    default:
      return null
  }
}

// Temple gestures → contract gestures. Double press is never mapped (the bridge leaves it to the system).
const GESTURE_FOR: Partial<Record<GlassesInput, Gesture>> = { tap: 'press', long_press: 'hold', scroll_down: 'swipe_down' }

const DOUBLE_TAP_ECHO_MS = 600

// Presenter shortcuts: Space = tap, H = hold, ↓ = swipe down. Ignored while typing.
const KEYS: Record<string, GlassesInput> = { ' ': 'tap', h: 'long_press', H: 'long_press', ArrowDown: 'scroll_down' }

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'SUMMARY'].includes(target.tagName)
}

function App() {
  const engine = useMemo(() => createEngine(engineUrl()), [])
  const [status, setStatus] = useState<BridgeStatus>('connecting')
  const [engineStatus, setEngineStatus] = useState<EngineStatus>('connecting')
  const [hud, setHud] = useState(() => ({ screen: currentScreen(), plan: currentPagePlan() }))
  const [messages, setMessages] = useState<ChatMessage[]>(() => [welcome()])
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<Step | null>(null)

  const say = (role: ChatMessage['role'], text: string) =>
    setMessages((m) => [...m, { id: nextMsgId++, role, text }])

  // Glasses bridge + lens state.
  useEffect(() => {
    log(`Standby ${BUILD} · engine ${engine.baseUrl}`)
    let stopVoice = () => {}
    let cancelled = false // StrictMode runs this effect twice in dev; only the surviving run starts the mic
    initGlasses(planScreen(INITIAL)).then((s) => {
      setStatus(s)
      if (s === 'connected' && !cancelled && !SHOT) stopVoice = startVoice(engine)
    })
    const offHud = subscribeHud((screen, plan) => setHud({ screen, plan }))
    return () => {
      cancelled = true
      stopVoice()
      offHud()
    }
  }, [engine])

  // Every event feeds the chat, the lens and the highlighted demo step.
  useEffect(
    () =>
      subscribe((e) => {
        const next = stepFor(e)
        if (next === 'reset') setStep(null)
        else if (next) setStep(next)
        if (e.type === 'demo.reset') setMessages([welcome()])
        const line = eventToChat(e)
        if (line) setMessages((m) => [...m, { id: nextMsgId++, ...line }])
        if (e.type === 'hud.screen') showScreen(fromEngine(e.data), e.data.clear_after_s)
      }),
    [],
  )

  // Live engine connection (skipped for DEV ?shot previews, so the preview stays on screen).
  useEffect(() => {
    if (SHOT) return
    return connectEngine(engine.baseUrl, publish, (s) => {
      setEngineStatus(s)
      // Say so on the lens instead of looking frozen; the engine replays the real screen on reconnect.
      if (s === 'offline') showScreen(offlineScreen())
    })
  }, [engine])

  // Gestures (temple, mirror buttons or keyboard) act on whatever screen is showing right now.
  useEffect(() => {
    let lastDoubleTap = -Infinity
    return onGlassesInput((input) => {
      // The simulator follows every DOUBLE_CLICK with a CLICK; that echo must not start or approve anything.
      if (input === 'double_tap') {
        lastDoubleTap = performance.now()
        return
      }
      if (input === 'tap' && performance.now() - lastDoubleTap < DOUBLE_TAP_ECHO_MS) {
        log('tap ignored: echo of a double tap')
        return
      }
      const gesture = GESTURE_FOR[input]
      if (gesture) void handleGesture(engine, gesture)
    })
  }, [engine])

  // Presenter shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const input = KEYS[e.key]
      if (!input || e.repeat || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return
      e.preventDefault()
      emitInput(input)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /** Run an engine request; failures show in chat. */
  async function call(fn: () => Promise<unknown>) {
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      say('system', `⚠ ${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const simulate = () =>
    call(async () => {
      const r = await engine.simulateCancel()
      if (!r.handled) say('system', 'The demo is already running. Reset it first.')
    })
  const reset = () => call(() => engine.reset())

  function handleSend(text: string) {
    say('user', text)
    const t = text.toLowerCase()
    if (/\b(reset|reinicia)\b/.test(t)) void reset()
    else if (/\b(simulate|start|cancel|cancelled|cancela)\b/.test(t)) void simulate()
    else say('agent', HELP)
  }

  return (
    <main className="app">
      <header className="hero">
        <h1>Standby.</h1>
        <p className="hero-sub">
          Airlines fix the flight. Nobody fixes the rest of your night. Standby rebooks you tonight and phones the
          places that have no API, asking you on the glasses before any spend.
        </p>
      </header>

      <div className="layout">
        <div className="col-left">
          <FlowSteps active={step} busy={busy} onSimulate={() => void simulate()} onReset={() => void reset()} />
          <ChatPanel messages={messages} onSend={handleSend} />
        </div>
        <div className="col-right">
          <HudMirror
            screen={hud.screen}
            plan={hud.plan}
            status={status}
            engineStatus={SHOT ? 'offline' : engineStatus}
            onInput={emitInput}
          />
        </div>
      </div>

      <footer className="footer">
        <details className="devtools" open={DEV_OPEN}>
          <summary>Developer tools</summary>
          {import.meta.env.DEV && <DevPanel />}
          <VoiceTester engine={engine} />
          <DebugLog />
        </details>
        <span className="build">
          {BUILD} · {engine.baseUrl}
        </span>
      </footer>
    </main>
  )
}

export default App
