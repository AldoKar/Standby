import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { hudText, IDLE_HUD, mockReply, type AgentReply } from './chat/mockAgent'
import { ChatPanel, type ChatMessage } from './components/ChatPanel'
import { DebugLog } from './components/DebugLog'
import { HudMirror } from './components/HudMirror'
import { log } from './debug/logger'
import {
  emitInput,
  initGlasses,
  onGlassesInput,
  renderToGlasses,
  type BridgeStatus,
  type GlassesInput,
} from './glasses/bridge'

const BUILD = `build ${__BUILD_ID__}`
const INITIAL_HUD = hudText([...IDLE_HUD, BUILD])

let nextMsgId = 1

function App() {
  const [status, setStatus] = useState<BridgeStatus>('connecting')
  const [hud, setHud] = useState(INITIAL_HUD)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: nextMsgId++, role: 'agent', text: 'Hi, I am Handle It. Where do you want to go?' },
  ])
  // What a tap on the glasses does right now. A ref so the gesture listener never reads stale state.
  const pendingTap = useRef<AgentReply | undefined>(undefined)

  const showReply = useCallback((reply: AgentReply) => {
    setMessages((m) => [...m, { id: nextMsgId++, role: 'agent', text: reply.chat }])
    const text = hudText(reply.hud)
    setHud(text)
    renderToGlasses(text)
    pendingTap.current = reply.onTap
  }, [])

  useEffect(() => {
    log(`Handle It ${BUILD}`)
    initGlasses(INITIAL_HUD).then(setStatus)
  }, [])

  useEffect(
    () =>
      onGlassesInput((input: GlassesInput) => {
        if (input === 'tap') {
          const next = pendingTap.current
          if (next) {
            setMessages((m) => [...m, { id: nextMsgId++, role: 'system', text: '👓 Tap on glasses' }])
            showReply(next)
          }
        } else if (input === 'double_tap') {
          // Double tap = no / back: clear the pending action and go idle.
          pendingTap.current = undefined
          const text = hudText(IDLE_HUD)
          setHud(text)
          renderToGlasses(text)
        }
      }),
    [showReply],
  )

  function handleSend(text: string) {
    setMessages((m) => [...m, { id: nextMsgId++, role: 'user', text }])
    showReply(mockReply(text))
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Handle It</h1>
        <span className="build">{BUILD}</span>
      </header>
      <div className="columns">
        <HudMirror text={hud} status={status} onInput={emitInput} />
        <ChatPanel messages={messages} onSend={handleSend} />
      </div>
      <DebugLog />
    </main>
  )
}

export default App
