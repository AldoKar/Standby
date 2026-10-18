import type { CSSProperties } from 'react'
import type { EngineStatus } from '../engine/client'
import type { Gesture } from '../engine/types'
import type { BridgeStatus, GlassesInput } from '../glasses/bridge'
import { imageMirrorUrl } from '../hud/images'
import { LENS_H, LENS_W, PADDING, type PagePlan } from '../hud/layout'
import { screenSummary, type HudScreen } from '../hud/screens'

type Props = {
  screen: HudScreen
  plan: PagePlan // includes the current animation frame
  status: BridgeStatus
  engineStatus: EngineStatus
  onInput: (input: GlassesInput) => void
}

const STATUS_LABEL: Record<BridgeStatus, string> = {
  connecting: 'Connecting to glasses…',
  connected: 'Connected · G2',
  browser: 'Mirror only · no glasses',
  error: 'Glasses error · see developer log',
}

const ENGINE_LABEL: Record<EngineStatus, string> = {
  connecting: 'Engine · connecting',
  live: 'Engine · live',
  offline: 'Engine · offline, retrying',
}

// Mirror buttons → the same glasses inputs the temple produces.
const BUTTONS: { input: GlassesInput; gesture: Gesture; label: string; key: string }[] = [
  { input: 'tap', gesture: 'press', label: 'Tap', key: 'Space' },
  { input: 'long_press', gesture: 'hold', label: 'Hold', key: 'H' },
  { input: 'scroll_down', gesture: 'swipe_down', label: 'Swipe down', key: '↓' },
]

/** What a gesture does on this screen, including the local tap-then-confirm step (mirrors hud/gestures.ts). */
function gestureMeaning(s: HudScreen, g: Gesture): string | undefined {
  if (s.confirm) return g === 'press' || g === 'hold' ? 'confirm' : 'back'
  if (g === 'press' && s.tapConfirms) return 'approve'
  return s.gestures[g]
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
export function HudMirror({ screen, plan, status, engineStatus, onInput }: Props) {
  return (
    <section className="stage" aria-labelledby="hud-title">
      <div className="stage-top">
        <h2 id="hud-title" className="stage-label">
          Lens view
        </h2>
        <span className="stage-statuses">
          <span className={`stage-status status-${status}`}>
            <span className="status-dot" aria-hidden="true" /> {STATUS_LABEL[status]}
          </span>
          <span className={`stage-status engine-${engineStatus}`}>
            <span className="status-dot" aria-hidden="true" /> {ENGINE_LABEL[engineStatus]}
          </span>
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
              // A container with its own border level (the app margin) carries no text: its border sets the look.
              opacity: t.borderLevel !== undefined ? 1 : t.color / 4,
              borderColor: t.borderLevel !== undefined ? `rgba(61, 255, 110, ${t.borderLevel / 15})` : undefined,
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
        {BUTTONS.map((b) => {
          const meaning = gestureMeaning(screen, b.gesture)
          return (
            <button
              key={b.input}
              type="button"
              className="gesture"
              disabled={!meaning}
              onClick={() => onInput(b.input)}
            >
              {b.label}
              {meaning ? ` · ${meaning}` : ''} <kbd>{b.key}</kbd>
            </button>
          )
        })}
      </div>
    </section>
  )
}
