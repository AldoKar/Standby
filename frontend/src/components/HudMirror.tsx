import type { BridgeStatus, GlassesInput } from '../glasses/bridge'

type Props = {
  text: string
  status: BridgeStatus
  onInput: (input: GlassesInput) => void
}

const STATUS_LABEL: Record<BridgeStatus, string> = {
  connecting: 'Connecting to glasses…',
  connected: 'Connected (simulator / G2)',
  browser: 'Browser mode (mirror only)',
  error: 'Glasses error, check the log',
}

/** 576×288 monochrome green replica of the G2 lens. */
export function HudMirror({ text, status, onInput }: Props) {
  return (
    <section className="panel hud-panel" aria-labelledby="hud-title">
      <header className="panel-header">
        <h2 id="hud-title">Lens view</h2>
        <span className={`status status-${status}`}>{STATUS_LABEL[status]}</span>
      </header>

      <div className="lens" role="img" aria-label={`Glasses display: ${text.replace(/\n/g, ', ')}`}>
        <pre className="lens-text">{text}</pre>
      </div>

      <div className="hud-controls">
        <button type="button" onClick={() => onInput('tap')}>
          Tap
        </button>
        <button type="button" onClick={() => onInput('double_tap')}>
          Double tap
        </button>
      </div>
    </section>
  )
}
