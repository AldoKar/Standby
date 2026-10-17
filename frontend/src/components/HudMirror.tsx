import type { CSSProperties } from 'react'
import type { BridgeStatus, GlassesInput } from '../glasses/bridge'
import { imageMirrorUrl } from '../hud/images'
import { LENS_H, LENS_W, planScreen } from '../hud/layout'
import { screenSummary, type HudAction, type HudScreen } from '../hud/screens'

type Props = {
  screen: HudScreen
  status: BridgeStatus
  onInput: (input: GlassesInput) => void
}

const STATUS_LABEL: Record<BridgeStatus, string> = {
  connecting: 'Connecting to glasses…',
  connected: 'Connected (simulator / G2)',
  browser: 'Browser mode (mirror only)',
  error: 'Glasses error, check the log',
}

const ACTION_LABEL: Record<HudAction['kind'], string> = {
  approve: 'approve',
  reject: 'reject',
  accept_alert: 'yes, fix it',
  dismiss: 'no',
}

// Lens pixels → % of the mirror box, so the mirror scales with the column.
const box = (x: number, y: number, w: number, h: number): CSSProperties => ({
  left: `${(x / LENS_W) * 100}%`,
  top: `${(y / LENS_H) * 100}%`,
  width: `${(w / LENS_W) * 100}%`,
  height: `${(h / LENS_H) * 100}%`,
})

/** 576×288 replica of the G2 lens, drawn from the same PagePlan the glasses receive. */
export function HudMirror({ screen, status, onInput }: Props) {
  const plan = planScreen(screen)
  return (
    <section className="panel hud-panel" aria-labelledby="hud-title">
      <header className="panel-header">
        <h2 id="hud-title">Lens view</h2>
        <span className={`status status-${status}`}>{STATUS_LABEL[status]}</span>
      </header>

      <div className="lens" role="img" aria-label={`Glasses display: ${screenSummary(screen)}`}>
        {plan.texts.map((t) => (
          <div
            key={t.id}
            className={`lens-box${t.border ? ' lens-border' : ''}`}
            style={{ ...box(t.x, t.y, t.w, t.h), zIndex: t.z, opacity: t.color / 4 }}
          >
            {t.content}
          </div>
        ))}
        {plan.images.map((i) => (
          <img
            key={i.id}
            className="lens-img"
            alt=""
            src={imageMirrorUrl(i.key, i.w, i.h)}
            style={{ ...box(i.x, i.y, i.w, i.h), zIndex: i.z }}
          />
        ))}
      </div>

      <div className="hud-controls">
        <button type="button" onClick={() => onInput('tap')}>
          Tap{screen.onTap ? ` (${ACTION_LABEL[screen.onTap.kind]})` : ''}
        </button>
        <button type="button" onClick={() => onInput('long_press')}>
          Hold{screen.onReject ? ` (${ACTION_LABEL[screen.onReject.kind]})` : ''}
        </button>
        <button type="button" onClick={() => onInput('double_tap')}>
          Double tap (exit)
        </button>
      </div>
    </section>
  )
}
