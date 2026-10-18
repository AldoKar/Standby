import type { CSSProperties } from 'react'
import type { BridgeStatus, GlassesInput } from '../glasses/bridge'
import { imageMirrorUrl } from '../hud/images'
import { LENS_H, LENS_W, PADDING, type PagePlan } from '../hud/layout'
import { screenSummary, type HudAction, type HudScreen } from '../hud/screens'

type Props = {
  screen: HudScreen
  plan: PagePlan // includes the current animation frame
  status: BridgeStatus
  onInput: (input: GlassesInput) => void
}

const STATUS_LABEL: Record<BridgeStatus, string> = {
  connecting: 'Connecting to glasses…',
  connected: 'Connected · G2',
  browser: 'Mirror only · no glasses',
  error: 'Glasses error · see developer log',
}

const ACTION_LABEL: Record<HudAction['kind'], string> = {
  approve: 'approve',
  reject: 'reject',
  accept_alert: 'yes',
  dismiss: 'no',
}

// Lens pixels → % of the mirror box, so the mirror scales with the column.
const box = (x: number, y: number, w: number, h: number): CSSProperties => ({
  left: `${(x / LENS_W) * 100}%`,
  top: `${(y / LENS_H) * 100}%`,
  width: `${(w / LENS_W) * 100}%`,
  height: `${(h / LENS_H) * 100}%`,
})

/**
 * Dark dot-grid stage (Even Realities style) holding a 1:1 replica of the 576×288 lens.
 * Nothing is added *inside* the lens: it shows exactly the PagePlan the glasses receive.
 */
export function HudMirror({ screen, plan, status, onInput }: Props) {
  return (
    <section className="stage" aria-labelledby="hud-title">
      <div className="stage-top">
        <h2 id="hud-title" className="stage-label">
          Lens view
        </h2>
        <span className={`stage-status status-${status}`}>
          <span className="status-dot" aria-hidden="true" /> {STATUS_LABEL[status]}
        </span>
      </div>

      <div className="lens" role="img" aria-label={`Glasses display: ${screenSummary(screen)}`}>
        {plan.texts.map((t) => (
          <div
            key={t.id}
            className={`lens-box${t.border ? ' lens-border' : ''}`}
            style={{
              ...box(t.x, t.y, t.w, t.h),
              zIndex: t.z,
              opacity: t.color / 4,
              padding: `calc(100cqw * ${t.padding ?? PADDING} / ${LENS_W})`,
              borderRadius: t.border ? `calc(100cqw * ${t.radius ?? 10} / ${LENS_W})` : undefined,
            }}
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

      <div className="gestures" role="group" aria-label="Glasses gestures">
        <button type="button" className="gesture" onClick={() => onInput('tap')}>
          Tap{screen.onTap ? ` · ${ACTION_LABEL[screen.onTap.kind]}` : ''} <kbd>Space</kbd>
        </button>
        <button type="button" className="gesture" onClick={() => onInput('long_press')}>
          Hold{screen.onReject ? ` · ${ACTION_LABEL[screen.onReject.kind]}` : ''} <kbd>H</kbd>
        </button>
        <button type="button" className="gesture" onClick={() => onInput('double_tap')}>
          Double tap · exit <kbd>Esc</kbd>
        </button>
      </div>
    </section>
  )
}
