// The demo flow as an Even-style step list (left column). The running step is highlighted from events.
import type { ReactNode } from 'react'

export type Step = 1 | 2 | 3 | 4

type Props = {
  active: Step | null
  busy: boolean
  onSimulate: () => void
  onReset: () => void
}

const icon = (d: ReactNode) => (
  <svg className="act-icon" viewBox="0 0 24 24" aria-hidden="true">
    {d}
  </svg>
)

const STEPS: { n: Step; title: string; description: string; icon: ReactNode }[] = [
  {
    n: 1,
    title: 'Cancelled',
    description: 'UA183 is cancelled. Standby checks tonight\'s fares and asks once: fix it for up to $300?',
    icon: icon(<path d="M12 3l9 17H3z M12 10v4 M12 17v.5" />),
  },
  {
    n: 2,
    title: 'Rebook',
    description: 'Three flights fit the limit. Swipe to pick one, tap, then tap again to book.',
    icon: icon(<path d="M2 13l7-1 5-8h2l-3 8h5l2-3h2l-1 4 1 4h-2l-2-3h-5l3 8h-2l-5-8-7-1z" />),
  },
  {
    n: 3,
    title: 'Call',
    description: 'The guesthouse desk closes at 11. Standby calls, and asks you before any fee.',
    icon: icon(<path d="M6 3c-1 6 3 12 9 14l3-3-3-3-2 2c-2-1-4-3-5-5l2-2-3-3z M15 3a6 6 0 0 1 6 6 M15 6a3 3 0 0 1 3 3" />),
  },
  {
    n: 4,
    title: 'Room held',
    description: 'Door code on the glasses; transcript and ledger saved.',
    icon: icon(<path d="M4 12l5 5L20 6" />),
  },
]

export function FlowSteps({ active, busy, onSimulate, onReset }: Props) {
  return (
    <section className="acts" aria-labelledby="flow-title">
      <h2 id="flow-title" className="section-label">
        Demo
      </h2>
      <ol className="act-list">
        {STEPS.map((s) => (
          <li
            key={s.n}
            className={`act${active === s.n ? ' act-active' : ''}`}
            aria-current={active === s.n ? 'step' : undefined}
          >
            <div className="act-title">
              {s.icon}
              <span>
                {s.n} · {s.title}
              </span>
            </div>
            <p className="act-desc">{s.description}</p>
            {s.n === 1 && (
              <div className="act-actions">
                <button type="button" className="btn" disabled={busy} onClick={onSimulate}>
                  Simulate cancellation
                </button>
              </div>
            )}
          </li>
        ))}
      </ol>
      <button type="button" className="btn-link" disabled={busy} onClick={onReset}>
        Reset demo
      </button>
    </section>
  )
}
