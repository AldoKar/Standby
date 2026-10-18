// Judge-facing panels under the main two columns: mandate ledger, policy trace, phone call, tests, activity.
// Same data as the P4 dashboard (dashboard/index.html), in Standby's Even-style design.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { formatTime } from '../chat/eventText'
import type { Engine } from '../engine/client'
import type { Ledger, TestsResult } from '../engine/types'
import { usd, VIA, type InsightsState, type SpendCheck } from './state'

type Tone = 'good' | 'bad' | 'ask' | 'neutral'

const Chip = ({ tone, children }: { tone: Tone; children: ReactNode }) => (
  <span className={`chip chip-${tone}`}>{children}</span>
)

const clock = (ts?: string) =>
  ts ? new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : ''

function Card({ title, wide, children }: { title: string; wide?: boolean; children: ReactNode }) {
  return (
    <section className={`card${wide ? ' card-wide' : ''}`} aria-label={title}>
      <h3 className="section-label">{title}</h3>
      {children}
    </section>
  )
}

// ---------- mandate ledger ----------

function LedgerCard({ ledger }: { ledger: Ledger | null }) {
  if (!ledger) return <Card title="Mandate ledger"><p className="muted">Waiting for the engine…</p></Card>
  const m = ledger.mandate
  return (
    <Card title="Mandate ledger">
      <div className="big-number">
        {usd(ledger.remaining_usd)} <span className="muted">left of {usd(m.budget_usd)}</span>
      </div>
      <table className="ledger-table">
        <tbody>
          <tr>
            <td>Budget</td>
            <td className="num">{usd(m.budget_usd)}</td>
          </tr>
          {ledger.spends.map((s) => (
            <tr key={s.reference}>
              <td>
                {s.merchant} <span className="muted">{s.kind}</span>
                {s.signature?.verified && <span className="muted"> · signed</span>}
              </td>
              <td className="num">{usd(s.amount)}</td>
            </tr>
          ))}
          {ledger.refunds.map((r) => (
            <tr key={`${r.airline}-${r.ts}`}>
              <td>
                {r.airline} refund <span className="muted">{r.status}</span>
              </td>
              <td className="num">−{usd(r.amount)}</td>
            </tr>
          ))}
          <tr className="sum">
            <td>Spent</td>
            <td className="num">{usd(ledger.spent_usd)}</td>
          </tr>
          <tr className="sum">
            <td>Net cost after refunds</td>
            <td className="num">{usd(ledger.net_cost_usd)}</td>
          </tr>
          {ledger.denied.map((d) => (
            <tr key={`${d.merchant}-${d.ts}`}>
              <td>
                <Chip tone="bad">Denied</Chip> {d.merchant} <span className="muted">{d.reason}</span>
              </td>
              <td className="num">{usd(d.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4 className="sub-label">Consent records</h4>
      <ul className="plain-list">
        {ledger.consents.length === 0 && <li className="muted">None yet.</li>}
        {ledger.consents.map((c) => (
          <li key={c.approval_id}>
            <Chip tone={c.approved ? 'good' : 'bad'}>{c.approved ? 'OK' : 'No'}</Chip> {usd(c.amount)} {c.merchant}{' '}
            <span className="muted">
              on {VIA[c.gesture] ?? c.gesture} · {clock(c.ts)}
            </span>
          </li>
        ))}
      </ul>
      <p className="fine-print">
        “{m.instruction}” · Agent token {m.token_id} · {m.label}
      </p>
    </Card>
  )
}

// ---------- policy trace ----------

const verdictChip = (v: string) =>
  v === 'pick' ? <Chip tone="good">Pick</Chip> : v === 'rejected' ? <Chip tone="bad">Rejected</Chip> : <Chip tone="neutral">OK</Chip>

const checkChip = (r: string) =>
  r === 'allow' ? <Chip tone="good">Allowed</Chip> : r === 'deny' ? <Chip tone="bad">Denied</Chip> : <Chip tone="ask">Ask the wearer</Chip>

function CheckRow({ k }: { k: SpendCheck }) {
  const label = k.kind === 'booking' ? 'Booking' : k.kind === 'fee' ? 'Fee' : k.kind
  return (
    <li>
      {checkChip(k.result)}{' '}
      <strong>
        {label} {usd(k.amount)}
        {k.merchant ? ` · ${k.merchant}` : ''}
      </strong>{' '}
      <span>{k.reason}</span>{' '}
      {k.answer ? (
        <Chip tone={k.answer.ok ? 'good' : 'bad'}>
          {k.answer.ok ? 'Approved' : 'Declined'} on {VIA[k.answer.via] ?? k.answer.via}
        </Chip>
      ) : (
        k.result === 'ask' && <Chip tone="neutral">Waiting for the wearer</Chip>
      )}{' '}
      <span className="muted small">{usd(k.remaining)} left before this spend</span>
    </li>
  )
}

function TraceCard({ s }: { s: InsightsState }) {
  const c = s.cancelled
  const offer = c?.airline_offer
  return (
    <Card title="Policy trace: why each option was picked or rejected" wide>
      <p className="trace-context">
        {c && offer ? (
          <>
            <strong>
              {c.flight} {c.route} cancelled.
            </strong>{' '}
            {offer.airline}'s own offer: {offer.flight} at {formatTime(offer.departs)} {offer.day}
            {offer.price_usd === 0 ? ', free' : ''}.
            {s.declined && ` Turned it down, so the ${usd(s.declined.refund_usd)} refund is automatic (${s.declined.status}).`}
          </>
        ) : (
          !s.options.length && <span className="muted">Waiting for a cancellation. Tap on the glasses, or press Simulate cancellation.</span>
        )}
      </p>
      {s.options.length > 0 && (
        <div className="table-scroll">
          <table className="options-table">
            <thead>
              <tr>
                <th>Option</th>
                <th>Departs → lands</th>
                <th className="num">Price</th>
                <th>Decision</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {s.options.map((o) => (
                <tr key={o.id} className={`opt-${o.verdict}`}>
                  <td className="opt">
                    {o.airline} {o.flight}
                  </td>
                  <td className="when">
                    {formatTime(o.departs)} → {formatTime(o.arrives)} {o.day}
                  </td>
                  <td className="num">{usd(o.price_usd)}</td>
                  <td>{verdictChip(o.verdict)}</td>
                  <td>{o.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h4 className="sub-label">Every spend, checked against the mandate</h4>
      <ul className="check-list">
        {s.checks.length === 0 && <li className="muted">No spends checked yet.</li>}
        {s.checks.map((k, i) => (
          <CheckRow key={`${k.kind}-${k.amount}-${i}`} k={k} />
        ))}
      </ul>
      <p className="fine-print">
        Decided in code (<code>engine/app/policy.py</code>). The LLM never decides a spend and never sees card data.
      </p>
    </Card>
  )
}

// ---------- phone call ----------

function CallCard({ s, recordedUrl, nudge }: { s: InsightsState; recordedUrl: string; nudge: string | null }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [fileUrl, setFileUrl] = useState<string | null>(null)
  const [missing, setMissing] = useState(false)
  const o = s.call.outcome

  let status: ReactNode
  if (o?.error) status = <Chip tone="bad">The call didn't start</Chip>
  else if (o) status = o.held ? <Chip tone="good">Room held</Chip> : <Chip tone="bad">Room not held</Chip>
  else if (s.call.waiting) status = <Chip tone="ask">Waiting for the wearer</Chip>
  else if (s.call.started) status = <Chip tone="neutral">● On the call</Chip>
  else status = <span className="muted">No call yet. The agent calls after the flight is booked.</span>

  const toggle = () => {
    const a = audio.current
    if (!a) return
    if (a.paused) void a.play()
    else a.pause()
  }

  return (
    <Card title="Phone call to the guesthouse">
      <div className="call-status" aria-live="polite">
        {status} {s.callMode && <span className="muted small">call: {s.callMode}</span>}
      </div>
      <ol className="plain-list steps">
        {s.call.steps.map((st, i) => (
          <li key={`${st.ts}-${i}`}>
            <span className="muted small">{clock(st.ts)}</span> {st.text}
          </li>
        ))}
      </ol>
      {o?.error && <p className="error-text">{o.error}</p>}
      {o && !o.error && (
        <>
          <dl className="outcome">
            <dt>Door code</dt>
            <dd>{o.door_code || '—'}</dd>
            <dt>Contact</dt>
            <dd>{o.contact || '—'}</dd>
            <dt>Fee agreed</dt>
            <dd>{o.fee_usd != null ? usd(o.fee_usd) : '—'}</dd>
            <dt>Checked against transcript</dt>
            <dd>{s.call.verified ? <Chip tone="good">Verified</Chip> : <Chip tone="neutral">Not verified</Chip>}</dd>
          </dl>
          {o.summary && <p className="small">{o.summary}</p>}
          {o.issues && o.issues.length > 0 && (
            <ul className="issues muted small">
              {o.issues.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          )}
          {s.call.transcriptUrl && /^https?:\/\//.test(s.call.transcriptUrl) && (
            <p className="small">
              <a href={s.call.transcriptUrl} target="_blank" rel="noopener noreferrer">
                Transcript
              </a>
            </p>
          )}
        </>
      )}
      <div className="recorded">
        <div className="recorded-row">
          <button type="button" className={`btn btn-primary${nudge ? ' nudge' : ''}`} onClick={toggle}>
            {playing ? '❚❚ Pause recorded call' : '▶ Play recorded call'}
          </button>
          <label className="btn">
            Other file…
            <input
              type="file"
              accept="audio/*"
              className="sr-only"
              onChange={(ev) => {
                const f = ev.target.files?.[0]
                if (f) {
                  setFileUrl(URL.createObjectURL(f))
                  setMissing(false)
                }
              }}
            />
          </label>
        </div>
        <audio
          ref={audio}
          controls
          preload="metadata"
          src={fileUrl ?? recordedUrl}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onError={() => !fileUrl && setMissing(true)}
        />
        <p className="fine-print">
          {missing
            ? 'Recording not found on the engine (dashboard/recorded-call.mp3). Pick it with "Other file…".'
            : (nudge ?? 'Fallback if the live call fails: a call recorded earlier.')}
        </p>
      </div>
    </Card>
  )
}

// ---------- tests ----------

function TestsCard({ engine }: { engine: Engine }) {
  const [tests, setTests] = useState<TestsResult | null>(null)
  const [error, setError] = useState(false)

  const refresh = () => {
    engine
      .tests()
      .then((t) => {
        setTests(t)
        setError(false)
      })
      .catch(() => setError(true))
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 60_000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine])

  const total = tests?.total ?? tests?.cases.length ?? 0
  const passed = tests?.passed ?? tests?.cases.filter((c) => c.passed).length ?? 0
  const pct = total ? Math.round((100 * passed) / total) : 0

  return (
    <Card title="Tests">
      {tests && !error ? (
        <>
          <div className="big-number">
            {passed} / {total} <span className="muted">passing · {pct}%</span>
          </div>
          <div className="meter" role="img" aria-label={`${passed} of ${total} tests passing`}>
            <span style={{ width: `${pct}%` }} />
          </div>
          <ul className="plain-list">
            {tests.cases.map((c) => (
              <li key={c.name}>
                <Chip tone={c.passed ? 'good' : 'bad'}>{c.passed ? 'Pass' : 'Fail'}</Chip> {c.name}
                {!c.passed && c.detail && <div className="muted small">{c.detail}</div>}
              </li>
            ))}
          </ul>
          {tests.ran_at && <p className="fine-print">Ran at {clock(tests.ran_at)}</p>}
        </>
      ) : (
        <p className="muted small">
          No results yet. Run <code>python test_engine.py</code> in <code>engine/</code>, then Refresh.
        </p>
      )}
      <button type="button" className="btn-link" onClick={refresh}>
        Refresh
      </button>
    </Card>
  )
}

// ---------- activity ----------

function ActivityCard({ s }: { s: InsightsState }) {
  return (
    <Card title="Activity (every engine event)" wide>
      <ol className="feed">
        {s.feed.length === 0 && <li className="muted">No events yet.</li>}
        {s.feed.map((f) => (
          <li key={f.id}>
            <span className="muted small">{clock(f.ts)}</span> <strong>{f.type}</strong> {f.text}
          </li>
        ))}
      </ol>
    </Card>
  )
}

// ---------- the section ----------

export function Insights({ s, ledger, engine, nudge }: { s: InsightsState; ledger: Ledger | null; engine: Engine; nudge: string | null }) {
  return (
    <section id="insights" className="insights" aria-labelledby="insights-title">
      <h2 id="insights-title" className="insights-title">
        Behind the glasses
      </h2>
      <p className="hero-sub insights-sub">
        What Standby decided, paid and said on the phone, live from the engine. Every number below comes from code,
        not from an LLM.
      </p>
      <div className="insights-grid">
        <LedgerCard ledger={ledger} />
        <TraceCard s={s} />
        <CallCard s={s} recordedUrl={engine.recordedCallUrl} nudge={nudge} />
        <TestsCard engine={engine} />
        <ActivityCard s={s} />
      </div>
    </section>
  )
}
