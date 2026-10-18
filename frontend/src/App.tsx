import type { Envelope, EventType } from '@contracts/events'
import { useEffect, useState } from 'react'
import './App.css'
import { eventToChat } from './chat/eventText'
import { parseMessage } from './chat/parseMessage'
import { ActsList, type Act } from './components/ActsList'
import { ChatPanel, type ChatMessage } from './components/ChatPanel'
import { DebugLog } from './components/DebugLog'
import { HudMirror } from './components/HudMirror'
import { log } from './debug/logger'
import { DevPanel } from './dev/DevPanel'
import { DESIGN_SHOTS, GLYPH_PROBE_LINES, SAMPLE_EVENTS } from './dev/sampleEvents'
import { publish, subscribe } from './events/bus'
import { transport, type SimulateKind } from './events/transport'
import { emitInput, initGlasses, onGlassesInput, type BridgeStatus, type GlassesInput } from './glasses/bridge'
import { performAction } from './hud/actions'
import { currentPagePlan, currentScreen, showScreen, subscribeHud } from './hud/controller'
import { planScreen } from './hud/layout'
import { createScreenMapper, idleScreen, type HudScreen } from './hud/screens'

const BUILD = `build ${__BUILD_ID__}`
const DEMO_TRIP = { origin: 'LAX', dest: 'SFO', deadline: '22:00', max_price: 250 }
const HELP = 'Try "Get me to SF tomorrow before 10 PM, max $250", or use the demo steps.'

const params = new URLSearchParams(location.search)
// `?dev` opens the developer tools (also reachable from the footer toggle).
const DEV_OPEN = params.has('dev')
// DEV-only `?shot=<name>` paints one state on launch (for simulator screenshots). Stripped from prod builds.
// Accepts a design screen (DESIGN_SHOTS), an event type (SAMPLE_EVENTS), "glyphs",
// or "act1" / "act3" to start a live mock-backend run (then drive it with simulator taps).
const SHOT = import.meta.env.DEV ? params.get('shot') : null
const INITIAL: HudScreen =
  SHOT === 'glyphs'
    ? { header: 'GLYPH PROBE', lines: GLYPH_PROBE_LINES.slice(0, 2), detail: GLYPH_PROBE_LINES[2] }
    : idleScreen(BUILD)

// Recreated on reset: it remembers task kinds, trip and confirmations.
let toScreen = createScreenMapper()
// Once at module load, not in an effect: StrictMode re-runs effects and would overwrite newer screens.
showScreen(INITIAL)
let nextMsgId = 1
let shotPublished = false

const welcome = (): ChatMessage => ({ id: nextMsgId++, role: 'agent', text: 'Hi, I am Standby. Where do you want to go?' })

/** Which demo act an event belongs to (drives the highlighted step). Null = keep the current one. */
function actFor(e: Envelope, kinds: Map<string, 'book' | 'resolve'>): Act | null {
  switch (e.type) {
    case 'trip.requested':
      return 1
    case 'task.started':
      return e.data.kind === 'book' ? 1 : 3
    case 'gate.changed':
    case 'boarding.soon':
      return 2
    case 'flight.cancelled':
    case 'call.started':
    case 'call.completed':
    case 'task.resolved':
      return 3
    default:
      return e.task_id ? (kinds.get(e.task_id) === 'resolve' ? 3 : kinds.has(e.task_id) ? 1 : null) : null
  }
}
let taskKinds = new Map<string, 'book' | 'resolve'>()

// Keyboard shortcuts for presenting: Space = tap, H = hold, Esc = exit. Ignored while typing.
const KEYS: Record<string, GlassesInput> = { ' ': 'tap', h: 'long_press', H: 'long_press', Escape: 'double_tap' }

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'SUMMARY'].includes(target.tagName)
}

function App() {
  const [status, setStatus] = useState<BridgeStatus>('connecting')
  const [hud, setHud] = useState(() => ({ screen: currentScreen(), plan: currentPagePlan() }))
  const [messages, setMessages] = useState<ChatMessage[]>(() => [welcome()])
  const [busy, setBusy] = useState(false)
  const [act, setAct] = useState<Act | null>(null)

  const say = (role: ChatMessage['role'], text: string) =>
    setMessages((m) => [...m, { id: nextMsgId++, role, text }])

  // Glasses bridge + lens state.
  useEffect(() => {
    log(`Standby ${BUILD}`)
    initGlasses(planScreen(INITIAL)).then(setStatus)
    return subscribeHud((screen, plan) => setHud({ screen, plan }))
  }, [])

  // Every event feeds the chat, the lens and the highlighted demo act.
  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'task.started' && e.task_id) taskKinds.set(e.task_id, e.data.kind)
        const nextAct = actFor(e, taskKinds)
        if (nextAct) setAct(nextAct)
        const line = eventToChat(e)
        if (line) setMessages((m) => [...m, { id: nextMsgId++, ...line }])
        const next = toScreen(e)
        if (next) showScreen(next)
      }),
    [],
  )

  // DEV-only `?shot=<name>` publishes that screen's events once on launch.
  useEffect(() => {
    if (shotPublished || !SHOT) return
    shotPublished = true // StrictMode runs effects twice in dev
    if (SHOT === 'act1') void transport.requestTrip(DEMO_TRIP)
    else if (SHOT === 'act3') void transport.simulate('cancel')
    else if (SHOT in DESIGN_SHOTS) DESIGN_SHOTS[SHOT]().forEach(publish)
    else if (SHOT in SAMPLE_EVENTS) publish(SAMPLE_EVENTS[SHOT as EventType]())
  }, [])

  // Gestures act on whatever screen is showing right now.
  useEffect(
    () =>
      onGlassesInput((input) => {
        const s = currentScreen()
        if (input === 'tap' && s.onTap) void performAction(s.onTap)
        else if (input === 'long_press' && s.onReject) void performAction(s.onReject)
        // double_tap = exit, handled by the bridge. Never repurpose it.
      }),
    [],
  )

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

  /** Run a backend request; failures show in chat (the backend would answer 4xx). */
  async function call(fn: () => Promise<void>) {
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      say('system', `⚠ ${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const simulate = (what: SimulateKind) => call(() => transport.simulate(what))

  const reset = () =>
    call(async () => {
      await transport.reset()
      toScreen = createScreenMapper()
      taskKinds = new Map()
      setAct(null)
      setMessages([welcome()])
      showScreen(idleScreen(BUILD))
    })

  function handleSend(text: string) {
    say('user', text)
    const cmd = parseMessage(text)
    if (cmd.kind === 'trip') void call(() => transport.requestTrip(cmd.body))
    else if (cmd.kind === 'simulate') void simulate(cmd.what)
    else if (cmd.kind === 'reset') void reset()
    else say('agent', HELP)
  }

  return (
    <main className="app">
      <header className="hero">
        <h1>Standby.</h1>
        <p className="hero-sub">
          Your AI travel agent on Even G2. It books your trip, guides you at the airport and, when something goes wrong,
          picks up the phone.
        </p>
      </header>

      <div className="layout">
        <div className="col-left">
          <ActsList
            active={act}
            busy={busy}
            onBook={() => {
              say('user', 'Get me to SF tomorrow before 10 PM, max $250')
              void call(() => transport.requestTrip(DEMO_TRIP))
            }}
            onGate={() => void simulate('gate')}
            onBoarding={() => void simulate('boarding')}
            onCancel={() => void simulate('cancel')}
            onReset={() => void reset()}
          />
          <ChatPanel messages={messages} onSend={handleSend} />
        </div>
        <div className="col-right">
          <HudMirror screen={hud.screen} plan={hud.plan} status={status} onInput={emitInput} />
        </div>
      </div>

      <footer className="footer">
        <details className="devtools" open={DEV_OPEN}>
          <summary>Developer tools</summary>
          {import.meta.env.DEV && <DevPanel />}
          <DebugLog />
        </details>
        <span className="build">{BUILD}</span>
      </footer>
    </main>
  )
}

export default App
