// The three acts of the demo, styled like Even Realities' feature list.
// The act that is running is highlighted (derived from events), so the audience always knows where we are.
import type { ReactNode } from 'react'

export type Act = 1 | 2 | 3

type Props = {
  active: Act | null
  busy: boolean
  onBook: () => void
  onGate: () => void
  onBoarding: () => void
  onCancel: () => void
  onReset: () => void
}

const icon = (d: ReactNode) => (
  <svg className="act-icon" viewBox="0 0 24 24" aria-hidden="true">
    {d}
  </svg>
)

const ICONS: Record<Act, ReactNode> = {
  1: icon(<path d="M2 13l7-1 5-8h2l-3 8h5l2-3h2l-1 4 1 4h-2l-2-3h-5l3 8h-2l-5-8-7-1z" />),
  2: icon(<path d="M5 12h12M13 7l5 5-5 5" />),
  3: icon(
    <path d="M6 3c-1 6 3 12 9 14l3-3-3-3-2 2c-2-1-4-3-5-5l2-2-3-3z M15 3a6 6 0 0 1 6 6 M15 6a3 3 0 0 1 3 3" />,
  ),
}

type ActProps = {
  n: Act
  title: string
  description: string
  active: boolean
  children: ReactNode
}

function ActItem({ n, title, description, active, children }: ActProps) {
  return (
    <li className={`act${active ? ' act-active' : ''}`} aria-current={active ? 'step' : undefined}>
      <div className="act-title">
        {ICONS[n]}
        <span>
          {n} · {title}
        </span>
      </div>
      <p className="act-desc">{description}</p>
      <div className="act-actions">{children}</div>
    </li>
  )
}

export function ActsList({ active, busy, onBook, onGate, onBoarding, onCancel, onReset }: Props) {
  return (
    <section className="acts" aria-labelledby="acts-title">
      <h2 id="acts-title" className="section-label">
        Demo
      </h2>
      <ol className="act-list">
        <ActItem n={1} title="Book" description="Finds the best flight, you approve with one tap, it pays with Visa." active={active === 1}>
          <button type="button" className="btn" disabled={busy} onClick={onBook}>
            Book a trip
          </button>
        </ActItem>
        <ActItem n={2} title="Guide" description="Gate changes and boarding alerts, right in your view." active={active === 2}>
          <button type="button" className="btn" disabled={busy} onClick={onGate}>
            Gate change
          </button>
          <button type="button" className="btn" disabled={busy} onClick={onBoarding}>
            Boarding soon
          </button>
        </ActItem>
        <ActItem
          n={3}
          title="Resolve"
          description="Flight cancelled: it rebooks, pays and calls the airline for you."
          active={active === 3}
        >
          <button type="button" className="btn" disabled={busy} onClick={onCancel}>
            Cancel flight
          </button>
        </ActItem>
      </ol>
      <button type="button" className="btn-link" disabled={busy} onClick={onReset}>
        Reset demo
      </button>
    </section>
  )
}
