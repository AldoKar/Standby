import type { EventType } from '@contracts/events'
import { useState } from 'react'
import { publish } from '../events/bus'
import { showScreen } from '../hud/controller'
import { DESIGN_SHOTS, EVENT_TYPES, GLYPH_PROBE_LINES, SAMPLE_EVENTS } from './sampleEvents'

const SHOT_NAMES = Object.keys(DESIGN_SHOTS)

/** Inject contract events or whole design screens by hand to check lens + chat rendering. */
export function DevPanel() {
  const [type, setType] = useState<EventType>('approval.requested')
  const [shot, setShot] = useState(SHOT_NAMES[0])

  return (
    <section className="dev-panel" aria-label="Developer tools">
      <label htmlFor="dev-shot">Screen</label>
      <select id="dev-shot" value={shot} onChange={(e) => setShot(e.target.value)}>
        {SHOT_NAMES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button type="button" onClick={() => DESIGN_SHOTS[shot]().forEach(publish)}>
        Show
      </button>

      <label htmlFor="dev-event">Event</label>
      <select id="dev-event" value={type} onChange={(e) => setType(e.target.value as EventType)}>
        {EVENT_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <button type="button" onClick={() => publish(SAMPLE_EVENTS[type]())}>
        Send
      </button>

      <button
        type="button"
        onClick={() =>
          showScreen({ header: 'GLYPH PROBE', lines: GLYPH_PROBE_LINES.slice(0, 2), detail: GLYPH_PROBE_LINES[2] })
        }
      >
        Glyph probe
      </button>
    </section>
  )
}
