import { useState, type FormEvent } from 'react'
import type { Engine } from '../engine/client'
import { sayText } from './listener'

/** Type what you'd say to the glasses: same POST /voice path, minus speech-to-text. */
export function VoiceTester({ engine }: { engine: Engine }) {
  const [text, setText] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    const t = text.trim()
    if (!t) return
    sayText(engine, t)
    setText('')
  }

  return (
    <form className="dev-panel" onSubmit={submit} aria-label="Voice command tester">
      <label htmlFor="voice-text">Say</label>
      <input
        id="voice-text"
        className="voice-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder='e.g. "yes, book it" or "show me another flight"'
        autoComplete="off"
      />
      <button type="submit">Send</button>
    </form>
  )
}
