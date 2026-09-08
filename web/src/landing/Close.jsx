import React from 'react'
import metrics from '../metrics.json'
import { stagger, useMagnetic } from './hooks.js'

/* Act 05 - the close.

   Two links and a provenance strip. The strip is the part that matters: every
   number on this page came out of one command against one seed on one split,
   and saying which is cheaper than being asked. */

const REPO = 'https://github.com/SohamRandive/Praman'

export default function Close() {
  const primary = useMagnetic(0.2)

  return (
    <section className="lp-act lp-act-close" id="act-console">
      <p className="lp-index lp-rv" style={stagger(0)}>05 <span>The console</span></p>
      <h2 className="lp-h2 lp-display-2 lp-rv" style={stagger(1)}>
        The exception list
        <em> is the product.</em>
      </h2>
      <p className="lp-lede lp-lede-2 lp-rv" style={stagger(2)}>
        The console opens on a queue of twelve real disputes run through the real mesh,
        and the ugly ones are deliberately in it: a package blocked on a channel
        qualifier, a case routed to a human, a retrieval agent degraded, one dispute
        worth less than the cost of contesting it. A screen that only renders the happy
        path is hiding the work.
      </p>

      <div className="lp-actions lp-actions-lg lp-rv" style={stagger(3)}>
        <a className="lp-btn lp-btn-primary lp-btn-lg" href="#/console" ref={primary}>
          <span>Open the console</span>
          <span aria-hidden="true" className="lp-arrow">→</span>
        </a>
        <a className="lp-btn lp-btn-quiet lp-btn-lg" href={REPO} rel="noreferrer noopener" target="_blank">
          <span>Read the source</span>
          <span aria-hidden="true" className="lp-arrow">↗</span>
        </a>
      </div>

      <ul className="lp-scope lp-rv" style={stagger(4)}>
        <li>Defense only. Nothing in the repository is offense-capable, and the tests enforce it.</li>
        <li>The model drafts; it never decides. Contest or accept is <span className="lp-num">p &gt; C/A</span>.</li>
        <li>Every code path emits <span className="lp-num">action = "draft"</span>. Submission is a human act.</li>
        <li>No card numbers, no raw identifiers — salted hashes at the ingest boundary.</li>
        <li>Degradation is surfaced, never absorbed. A degraded agent shrinks the probability toward 0.5 and says so.</li>
      </ul>

      <footer className="lp-foot">
        <div className="lp-foot-brand">
          <span className="lp-deva">प्रमाण</span>
          <span>Praman — a valid means of knowledge</span>
        </div>
        <p className="lp-provenance lp-num">
          seed {metrics.provenance.seed} · {metrics.provenance.command} ·{' '}
          {metrics.provenance.split} · {metrics.economics.test_disputes.toLocaleString('en-IN')}{' '}
          disputes / {metrics.economics.test_merchants} merchants · corpus{' '}
          {metrics.provenance.corpus}
        </p>
      </footer>
    </section>
  )
}
