import React, { useEffect, useState } from 'react'
import cases from '../cases.json'
import metrics from '../metrics.json'
import { stagger, useCountUp, useReducedMotion } from './hooks.js'

/* Act 01 - the shape of the loss.

   The case on the right is not a mock-up. It is fixture case 2 of the twelve
   the console ships, run through the real mesh: a Visa 13.1 with a real
   window, a real checklist and the real numbers the expected-cost rule
   produced for it. The only synthetic thing on the panel is the clock, which
   counts down from the window the fixture recorded so that the deadline reads
   as a deadline rather than as a screenshot - and it says so on its own face. */

const CASE = cases[1]

function pad(n) {
  return String(Math.floor(n)).padStart(2, '0')
}

function Countdown({ hours, running }) {
  const reduced = useReducedMotion()
  const [remaining, setRemaining] = useState(hours * 3600)
  useEffect(() => {
    if (!running) return undefined
    // One interval, one second. A rAF countdown burns a frame to move a digit
    // that changes once a second.
    const id = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(id)
  }, [running])

  const d = remaining / 86400
  const h = (remaining % 86400) / 3600
  const m = (remaining % 3600) / 60
  const s = remaining % 60
  return (
    <span className="lp-clock" aria-live={reduced ? 'off' : undefined}>
      <b>{pad(d)}</b><i>d</i>
      <b>{pad(h)}</b><i>h</i>
      <b>{pad(m)}</b><i>m</i>
      <b className="lp-clock-s">{pad(s)}</b><i>s</i>
    </span>
  )
}

export default function Problem({ live }) {
  const elapsed = useCountUp(CASE.deadline.elapsed, live, { duration: 1800, delay: 260 })
  const gap = useCountUp(metrics.evidence.blocking_gap_rate, live, { duration: 1400 })
  const routed = useCountUp(metrics.evidence.routed_to_human_rate, live, { duration: 1400, delay: 120 })

  return (
    <section className="lp-act lp-act-problem" id="act-window">
      <div className="lp-act-head">
        <p className="lp-index lp-rv" style={stagger(0)}>01 <span>The window</span></p>
        <h2 className="lp-h2 lp-rv" style={stagger(1)}>
          The money left days ago.
          <em> What is left is a window.</em>
        </h2>
      </div>

      <div className="lp-two">
        <div className="lp-col-text">
          <p className="lp-body lp-rv" style={stagger(2)}>
            A chargeback debits first and argues later. By the time a merchant sees the
            notice, the funds are gone and the only remaining question is documentary:
            can the specific set of records this reason code accepts be produced, in
            the form it accepts them, before the window closes.
          </p>
          <p className="lp-body lp-rv" style={stagger(3)}>
            That question is not a judgement call and it is not a language problem. It
            is a lookup against a published matrix, a set of constraints evaluated over
            the artifacts actually on file, and an inequality over the amount at stake.
            Praman does the parts that are arithmetic with arithmetic — and reserves the
            model for the one job that is genuinely language: writing the narrative.
          </p>

          <dl className="lp-defs lp-rv" style={stagger(4)}>
            <div>
              <dt>{(gap * 100).toFixed(1)}%</dt>
              <dd>
                of held-out disputes carry a <b>blocking evidence gap</b> — a document
                the code requires that the merchant cannot produce. No classifier
                recovers those. The honest answer is to accept and stop spending.
              </dd>
            </div>
            <div>
              <dt>{(routed * 100).toFixed(1)}%</dt>
              <dd>
                route to a human because the matrix cannot resolve them — an unknown
                capture status, a qualifier that needs a person. Routed is
                <span className="lp-tint-indigo"> not a loss</span>, and the console
                never colours it as one.
              </dd>
            </div>
          </dl>
        </div>

        <aside className="lp-case lp-rv" style={stagger(5)}>
          <div className="lp-case-top">
            <div>
              <span className="lp-code">{CASE.reason_code}</span>
              <span className="lp-case-title">{CASE.title}</span>
            </div>
            <span className="lp-chip lp-chip-ochre">at risk</span>
          </div>

          <div className="lp-case-clock">
            <Countdown hours={CASE.deadline.total_hours} running={live} />
            <span className="lp-case-note">
              remaining of the {Math.round(CASE.deadline.window_hours)}-hour window ·
              fixture case, demo clock
            </span>
            <div className="lp-window">
              <span className="lp-window-fill" style={{ transform: `scaleX(${elapsed})` }} />
            </div>
          </div>

          <ul className="lp-checklist">
            {CASE.evidence.checklist.map((f, i) => (
              <li
                key={f.field}
                className={`lp-rv ${f.present ? 'lp-has' : 'lp-lacks'}`}
                style={stagger(i + 6, 70)}
              >
                <span className="lp-tick" aria-hidden="true" />
                <span className="lp-check-label">{f.label}</span>
                <span className="lp-check-req">{f.required ? 'required' : 'supporting'}</span>
              </li>
            ))}
          </ul>

          <div className="lp-case-foot">
            <div>
              <span className="lp-k">disputed</span>
              <b className="lp-num">{CASE.amount}</b>
            </div>
            <div>
              <span className="lp-k">cost to contest</span>
              <b className="lp-num">{CASE.contest_cost}</b>
            </div>
            <div>
              <span className="lp-k">p(win), calibrated</span>
              <b className="lp-num">{CASE.recommendation.p_win.toFixed(3)}</b>
            </div>
            <div>
              <span className="lp-k">break-even</span>
              <b className="lp-num lp-tint-verd">{CASE.recommendation.break_even.toFixed(3)}</b>
            </div>
          </div>
          <p className="lp-case-verdict">
            <span className="lp-chip lp-chip-verd">contest</span>
            <span>
              p exceeds C/A by a wide margin. Expected value of contesting:{' '}
              <b className="lp-num">{CASE.recommendation.expected_value}</b>.
            </span>
          </p>
        </aside>
      </div>
    </section>
  )
}
