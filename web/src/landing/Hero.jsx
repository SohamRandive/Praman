import React from 'react'
import metrics from '../metrics.json'
import { rupees, policy } from './money.js'
import { stagger, useCountUp, useMagnetic } from './hooks.js'

/* The opening claim, and the three figures that have to survive the panel.

   Every number on this page is read out of metrics.json, which is written by
   `make eval` against the held-out split. There is no second source, and
   nothing here is rounded by hand. */

function Figure({ value, format, label, sub, index, live }) {
  const v = useCountUp(value, live, { duration: 1600, delay: index * 120 })
  return (
    <div className="lp-fig" style={stagger(index + 6)}>
      <span className="lp-fig-v">{format(v)}</span>
      <span className="lp-fig-l">{label}</span>
      <span className="lp-fig-s">{sub}</span>
    </div>
  )
}

export default function Hero({ live }) {
  const rule = policy(metrics, 'expected_cost_rule')
  const console_ = useMagnetic(0.22)

  return (
    <header className="lp-hero">
      <div className="lp-hero-body">
        <p className="lp-eyebrow lp-rv" style={stagger(0)}>
          <span className="lp-deva">प्रमाण</span>
          <span className="lp-eyebrow-sep" aria-hidden="true" />
          pramāṇa — a valid means of knowledge
        </p>

        <h1 className="lp-display lp-rv" style={stagger(1)}>
          A merchant sees one dispute.
          <em> The aggregator sees the ring.</em>
        </h1>

        <p className="lp-lede lp-rv" style={stagger(2)}>
          Praman decides whether a disputed payment is worth contesting, assembles the
          evidence the specific reason code demands, finds the abuse rings that only
          become visible across merchants, and drafts the representment without
          inventing a single value. The decision itself is arithmetic, not a model.
        </p>

        <div className="lp-actions lp-rv" style={stagger(3)}>
          <a className="lp-btn lp-btn-primary" href="#/console" ref={console_}>
            <span>Open the console</span>
            <span aria-hidden="true" className="lp-arrow">→</span>
          </a>
          <a className="lp-btn lp-btn-quiet" href="#act-finding">
            <span>The counterintuitive part</span>
            <span aria-hidden="true" className="lp-arrow">↓</span>
          </a>
        </div>

        <div className="lp-strip lp-rv" style={stagger(4)}>
          <Figure
            index={0}
            live={live}
            value={rule.net_minor}
            format={rupees}
            label="net recovered by the decision rule"
            sub={`${metrics.economics.test_disputes.toLocaleString('en-IN')} held-out disputes · contest cost ${metrics.economics.cost}`}
          />
          <Figure
            index={1}
            live={live}
            value={metrics.rings.precision}
            format={(v) => v.toFixed(3)}
            label="ring precision"
            sub={`${metrics.rings.false_rings} false ring in ${metrics.rings.decoys} decoy groups`}
          />
          <Figure
            index={2}
            live={live}
            value={metrics.evidence.blocking_gap_rate}
            format={(v) => `${(v * 100).toFixed(1)}%`}
            label="carry a blocking evidence gap"
            sub={`${metrics.evidence.blocking_gap_count.toLocaleString('en-IN')} disputes that paperwork alone loses`}
          />
        </div>
      </div>

      <p className="lp-cue lp-rv" style={stagger(8)} aria-hidden="true">
        <span className="lp-cue-rule" />
        scroll
      </p>
    </header>
  )
}
