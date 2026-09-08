import React, { useEffect, useState } from 'react'
import cases from '../cases.json'
import metrics from '../metrics.json'
import { stagger, useInView, useReducedMotion } from './hooks.js'

/* Act 04 - the grounding verifier.

   The sentence on the left is the one the system actually emitted for fixture
   case 2, with its real citations. The sentence on the right is the failure the
   module exists for, taken from the decision record that introduced it: every
   citation resolves, the cited document is genuinely in the package, the
   tracking reference is real - and the date in the prose is not the date the
   document holds. A verifier that only resolves citations passes that to a bank.

   The animation is a reading order, not an effect: scan, resolve, judge. Under
   reduced motion it renders in its final state, because the verdict is the
   content and no one should have to wait for a transition to read it. */

const GOOD = cases.find((c) => c.draft)?.draft?.claims?.find((c) => c.field === 'shipping_proof')

/* The fault-injected counterpart, quoted exactly as the decision record states
   it. Nothing here is embellished: one sentence, one citation, one contradiction. */
const BAD = {
  text: 'The consignment was delivered on 2026-06-10.',
  token: '2026-06-10',
  citation: { ref: 'art_shipping_pro_a257a874.delivered_at', value: '2025-11-23' },
}

function split(text, tokens) {
  const pattern = new RegExp(`(${tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g')
  return text.split(pattern).filter(Boolean)
}

function Sheet({ title, tone, step, tokens, text, citations, verdict, note }) {
  const parts = split(text, tokens.map((t) => t.value))
  return (
    <figure className={`lp-sheet lp-tone-${tone}${step >= 1 ? ' lp-scanning' : ''}`}>
      <figcaption className="lp-sheet-cap">
        <span className="lp-k">{title}</span>
        <span className={`lp-stamp${step >= 3 ? ' lp-stamp-on' : ''}`}>{verdict}</span>
      </figcaption>
      <blockquote className="lp-claim">
        <span className="lp-scan" aria-hidden="true" />
        {parts.map((part, i) => {
          const hit = tokens.find((t) => t.value === part)
          if (!hit) return <span key={i}>{part}</span>
          const cls = step < 2 ? 'lp-tok' : hit.grounded ? 'lp-tok lp-tok-ok' : 'lp-tok lp-tok-bad'
          return <span key={i} className={cls}>{part}</span>
        })}
      </blockquote>
      <ul className={`lp-cites${step >= 2 ? ' lp-cites-on' : ''}`}>
        {citations.map((c, i) => (
          <li key={c.ref} style={stagger(i, 90)}>
            <span className="lp-cite-ref lp-num">{c.ref}</span>
            <span className="lp-cite-arrow" aria-hidden="true">→</span>
            <span className={`lp-cite-val lp-num${c.contradicts ? ' lp-tint-blood' : ''}`}>{c.value}</span>
          </li>
        ))}
      </ul>
      <p className="lp-sheet-note">{note}</p>
    </figure>
  )
}

export default function Verifier() {
  const reduced = useReducedMotion()
  const [ref, inView] = useInView({ threshold: 0.25 })
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (!inView) return undefined
    if (reduced) { setStep(3); return undefined }
    const timers = [
      setTimeout(() => setStep(1), 320),
      setTimeout(() => setStep(2), 1500),
      setTimeout(() => setStep(3), 2500),
    ]
    return () => timers.forEach(clearTimeout)
  }, [inView, reduced])

  const goodTokens = GOOD.citations.map((c) => ({ value: c.value, grounded: true }))

  return (
    <section
      className={`lp-act lp-act-verifier${inView ? ' lp-in' : ''}`}
      id="act-guardrail"
      ref={ref}
    >
      <div className="lp-act-head">
        <p className="lp-index lp-rv" style={stagger(0)}>04 <span>The guardrail</span></p>
        <h2 className="lp-h2 lp-rv" style={stagger(1)}>
          A fabrication is a real document,
          <em> cited correctly, beside a wrong value.</em>
        </h2>
      </div>

      <div className="lp-two lp-two-verifier">
        <div className="lp-col-text">
          <p className="lp-body lp-rv" style={stagger(2)}>
            The model in this system writes prose and nothing else. It holds no tools, no
            retrieval and no write authority, and it never decides anything — contest or
            accept is an inequality. Even inside that box, one failure remains available
            to it, and it is the one that reaches an issuer looking perfect.
          </p>
          <ol className="lp-checks lp-rv" style={stagger(3)}>
            <li><span className="lp-num">1</span> Every citation resolves to an artifact and a field actually in the package.</li>
            <li><span className="lp-num">2</span> Any value the sentence reports for a citation equals what the artifact holds.</li>
            <li className="lp-check-lead">
              <span className="lp-num">3</span> Every value-shaped token in the prose — a date, an amount, a
              reference — appears among the cited field values. Check 3 is the reason the
              module exists.
            </li>
          </ol>
          <p className="lp-body lp-body-s lp-rv" style={stagger(4)}>
            And when a strip drops required coverage, the draft is <b>blocked, not
            shortened</b>. Emitting the survivors reads fluent and complete; it also
            asserts less than the package promised, to a bank, on a merchant’s behalf.
          </p>
        </div>

        <div className="lp-sheets">
          <Sheet
            title="emitted — fixture case 2"
            tone="verd"
            step={step}
            text={GOOD.text}
            tokens={goodTokens}
            citations={GOOD.citations}
            verdict="grounded 1.00"
            note={`Three value-shaped tokens, three cited field values, all equal. Required-field coverage holds at 1.00 and the draft is released for human approval — action stays "draft" on every code path.`}
          />
          <Sheet
            title="fault injection — the case the module exists for"
            tone="blood"
            step={step}
            text={BAD.text}
            tokens={[{ value: BAD.token, grounded: false }]}
            citations={[{ ...BAD.citation, contradicts: true }]}
            verdict="unsupported_value → blocked"
            note="The citation resolves. The artifact is genuinely in the package. The date in the prose is not the date the artifact holds, so the claim is stripped — and because it carried a required field, coverage falls below 1.00 and the draft is refused and escalated rather than trimmed."
          />
        </div>
      </div>

      <ul className="lp-chips lp-rv" style={stagger(6)}>
        <li className="lp-chip-card">
          <span className="lp-k">model calls per case</span>
          <b className="lp-num">{metrics.system.model_calls_per_case.toFixed(2)}</b>
          <span className="lp-chip-note">
            {metrics.system.model_calls} calls across {metrics.system.cases} cases. Most
            disputes never reach a model: an accept needs no narrative.
          </span>
        </li>
        <li className="lp-chip-card">
          <span className="lp-k">drafts emitted / blocked</span>
          <b className="lp-num">{metrics.system.drafts_emitted} / {metrics.system.drafts_blocked}</b>
          <span className="lp-chip-note">
            In the measured run the templated provider fabricated nothing, so nothing was
            stripped. The block path above is exercised by fault injection, and that
            distinction is stated rather than blurred.
          </span>
        </li>
        <li className="lp-chip-card">
          <span className="lp-k">p95 decision latency</span>
          <b className="lp-num">{(metrics.system.p95_decision_s * 1000).toFixed(1)} ms</b>
          <span className="lp-chip-note">
            Five agents under one deadline budget, {metrics.system.cases} cases. In-process,
            single machine, stubbed retrieval — a floor, and reported as one.
          </span>
        </li>
      </ul>
    </section>
  )
}
