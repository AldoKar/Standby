import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { ChatRole } from '../chat/eventText'

export type ChatMessage = { id: number; role: ChatRole; text: string }

type Props = {
  messages: ChatMessage[]
  onSend: (text: string) => void
}

/** Agent = plain text, user = light bubble, system events = small timeline rows. */
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
    <section className="chat" aria-labelledby="chat-title">
      <h2 id="chat-title" className="section-label">
        Chat
      </h2>

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
        <button type="submit" className="btn btn-primary">
          Send
        </button>
      </form>
    </section>
  )
}
