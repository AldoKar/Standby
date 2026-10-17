import { useEffect, useState } from 'react'
import './App.css'
import { eventToChat } from './chat/eventText'
import { ChatPanel, type ChatMessage } from './components/ChatPanel'
import { DebugLog } from './components/DebugLog'
import { HudMirror } from './components/HudMirror'
import { log } from './debug/logger'
import { DevPanel } from './dev/DevPanel'
import type { EventType } from '@contracts/events'
import { DESIGN_SHOTS, eventsForMessage, GLYPH_PROBE_LINES, SAMPLE_EVENTS } from './dev/sampleEvents'
import { publish, subscribe } from './events/bus'
import { emitInput, initGlasses, onGlassesInput, type BridgeStatus } from './glasses/bridge'
import { performAction } from './hud/actions'
import { currentScreen, showScreen, subscribeHud } from './hud/controller'
import { planScreen } from './hud/layout'
import { createScreenMapper, idleScreen, type HudScreen } from './hud/screens'

const BUILD = `build ${__BUILD_ID__}`

// DEV-only `?shot=<name>` paints one state on launch (for simulator screenshots). Stripped from prod builds.
// Accepts a design screen (DESIGN_SHOTS), an event type (SAMPLE_EVENTS) or "glyphs".
const SHOT = import.meta.env.DEV ? new URLSearchParams(location.search).get('shot') : null
const INITIAL: HudScreen =
  SHOT === 'glyphs'
    ? { header: 'GLYPH PROBE', lines: GLYPH_PROBE_LINES.slice(0, 2), detail: GLYPH_PROBE_LINES[2] }
    : idleScreen(BUILD)

const toScreen = createScreenMapper()
// Once at module load, not in an effect: StrictMode re-runs effects and would overwrite newer screens.
showScreen(INITIAL)
let nextMsgId = 1
let shotPublished = false

function App() {
  const [status, setStatus] = useState<BridgeStatus>('connecting')
  const [screen, setScreen] = useState<HudScreen>(currentScreen)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: nextMsgId++, role: 'agent', text: 'Hi, I am Handle It. Where do you want to go?' },
  ])

  // Glasses bridge + lens state.
  useEffect(() => {
    log(`Handle It ${BUILD}`)
    initGlasses(planScreen(INITIAL)).then(setStatus)
    return subscribeHud(setScreen)
  }, [])

  // Every event feeds both columns: chat (long form) and lens (3-zone template).
  useEffect(
    () =>
      subscribe((e) => {
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
    if (SHOT in DESIGN_SHOTS) DESIGN_SHOTS[SHOT]().forEach(publish)
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

  function handleSend(text: string) {
    setMessages((m) => [...m, { id: nextMsgId++, role: 'user', text }])
    const events = eventsForMessage(text)
    if (events.length === 0) {
      setMessages((m) => [
        ...m,
        { id: nextMsgId++, role: 'agent', text: 'Try "book me a flight to SF", "gate", "boarding" or "cancel".' },
      ])
    }
    events.forEach(publish)
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Handle It</h1>
        <span className="build">{BUILD}</span>
      </header>
      <div className="columns">
        <HudMirror screen={screen} status={status} onInput={emitInput} />
        <ChatPanel messages={messages} onSend={handleSend} />
      </div>
      {import.meta.env.DEV && <DevPanel />}
      <DebugLog />
    </main>
  )
}

export default App
