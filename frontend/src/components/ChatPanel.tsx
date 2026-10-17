import { useEffect, useRef, useState, type FormEvent } from 'react'

export type ChatMessage = { id: number; role: 'user' | 'agent' | 'system'; text: string }

type Props = {
  messages: ChatMessage[]
  onSend: (text: string) => void
}

export function ChatPanel({ messages, onSend }: Props) {
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLOListElement>(null)

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages])

  function submit(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text) return
    onSend(text)
    setDraft('')
  }

  return (
    <section className="panel chat-panel" aria-labelledby="chat-title">
      <header className="panel-header">
        <h2 id="chat-title">Chat</h2>
      </header>

      <ol className="messages" ref={listRef} aria-live="polite">
        {messages.map((m) => (
          <li key={m.id} className={`msg msg-${m.role}`}>
            {m.text}
          </li>
        ))}
      </ol>

      <form className="composer" onSubmit={submit}>
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <input
          id="chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Get me to SF tomorrow before 10 PM, max $250"
          autoComplete="off"
        />
        <button type="submit">Send</button>
      </form>
    </section>
  )
}
