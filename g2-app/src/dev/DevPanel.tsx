import { useState } from 'react'
import { makeEvent, publish } from '../events/bus'
import { showScreen } from '../hud/controller'
import { GLYPH_PROBE_LINES, SAMPLE_SCREENS } from './sampleScreens'

const NAMES = Object.keys(SAMPLE_SCREENS)

/** Preview any engine screen locally (no engine call). The next live hud.screen replaces it. */
export function DevPanel() {
  const [name, setName] = useState(NAMES[0])

  return (
    <section className="dev-panel" aria-label="Developer tools">
      <label htmlFor="dev-screen">Preview screen</label>
      <select id="dev-screen" value={name} onChange={(e) => setName(e.target.value)}>
        {NAMES.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      <button type="button" onClick={() => publish(makeEvent('hud.screen', SAMPLE_SCREENS[name]))}>
        Show
      </button>
      <button
        type="button"
        onClick={() =>
          showScreen({
            id: 'glyphs',
            header: 'GLYPH PROBE',
            lines: GLYPH_PROBE_LINES.slice(0, 2),
            detail: GLYPH_PROBE_LINES[2],
            gestures: {},
          })
        }
      >
        Glyph probe
      </button>
    </section>
  )
}
