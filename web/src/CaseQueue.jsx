import React, { useMemo } from 'react'
import { decisionBreakdown, policy, pct, urgencyColour } from './format.js'

/* The landing screen.

   Every figure below is either read from `metrics.json` - written by
   `eval/run_eval.py` on the held-out test split - or derived in view from
   `cases.json`. There is no third source and no tile is permitted a placeholder:
   a KPI grid filled with plausible-looking numbers is worse than no KPI grid,
   because it is indistinguishable from a real one at a glance. */

const BASELINE_ORDER = ['accept_all', 'contest_all', 'naive_half', 'best_constant',
                        'expected_cost_rule']

function Tile({ label, value, unit, foot, tone }) {
  return (
    <div className={`tile${tone ? ` ${tone}` : ''}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value n">
        {value}
        {unit && <span className="tile-unit">{unit}</span>}
      </div>
      <div className="tile-foot">{foot}</div>
    </div>
  )
}

function StatusPill({ c }) {
  const refused = c.rejections.some((r) => r.constraint_id === 'email_channel_only')
  if (c.evidence.routing === 'route_to_human') {
    return <span className="pill routed">routed to a human</span>
  }
  if (refused) return <span className="pill failed">evidence refused</span>
  if (!c.evidence.sufficient) return <span className="pill failed">package blocked</span>
  if (c.below_cost) return <span className="pill quiet">below contest cost</span>
  if (c.agents.some((a) => a.status !== 'ok')) {
    return <span className="pill degraded">decided degraded</span>
  }
  return <span className="pill ok">package assembled</span>
}

export default function CaseQueue({ cases, metrics, onOpenCase }) {
  const rule = policy(metrics, 'expected_cost_rule')
  const breakdown = useMemo(() => decisionBreakdown(cases), [cases])
  const maxAmount = useMemo(() => Math.max(...cases.map((c) => c.amount_minor)), [cases])
  const ordered = useMemo(
    () => cases.map((c, i) => ({ c, i }))
      .sort((a, b) => a.c.deadline.total_hours - b.c.deadline.total_hours),
    [cases],
  )

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h2>Case queue</h2>
          <p className="screen-sub">
            Twelve disputes, sorted by filing deadline. The clock is no longer the
            hero of the screen, but it is still what forces the action.
          </p>
        </div>
      </header>

      <section className="kpi" aria-label="Measured results">
        <Tile
          label="Net recovered · expected-cost rule"
          value={rule.net}
          foot={`${metrics.economics.test_disputes.toLocaleString('en-IN')} held-out disputes across ${metrics.economics.test_merchants} merchants the model never saw`}
          tone="good"
        />
        <Tile
          label="Worth of the rule itself"
          value={metrics.economics.rule_vs_best_constant}
          foot="Against the best tuned constant threshold, not against 0.5 — ADR-012. The weaker comparison overstates it by an order of magnitude."
        />
        <Tile
          label="Ring precision"
          value={metrics.rings.precision.toFixed(3)}
          foot={`False-ring rate ${metrics.rings.false_ring_rate.toFixed(3)} — ${metrics.rings.false_rings} of ${metrics.rings.decoys} innocent clusters accused. Recall ${metrics.rings.recall.toFixed(3)}, and it is not the number with a floor.`}
        />
        <Tile
          label="Carrying a blocking evidence gap"
          value={pct(metrics.evidence.blocking_gap_rate, 1)}
          foot={`${metrics.evidence.blocking_gap_count.toLocaleString('en-IN')} disputes cannot assemble a package at all. A further ${pct(metrics.evidence.routed_to_human_rate, 1)} route to a human rather than being guessed at.`}
          tone="warn"
        />
      </section>

      <section className="baselines" aria-label="Policies compared">
        <h3 className="section-h">Every policy decides and settles on the same outcome</h3>
        <table className="ledger">
          <thead>
            <tr>
              <th>Policy</th>
              <th className="n">Net</th>
              <th className="n">Contested</th>
              <th className="n">False-positive cost</th>
            </tr>
          </thead>
          <tbody>
            {BASELINE_ORDER.map((key) => {
              const p = policy(metrics, key)
              const isRule = key === 'expected_cost_rule'
              return (
                <tr key={key} className={isRule ? 'lead' : ''}>
                  <td>{p.label}</td>
                  <td className="n">{p.net}</td>
                  <td className="n">{pct(p.contested_share)}</td>
                  <td className="n">{p.false_positive_cost}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="finding">
          <b>The trivial policy beats the ML policy.</b> A competent classifier at a
          naive threshold nets {policy(metrics, 'naive_half').net} against{' '}
          {policy(metrics, 'contest_all').net} for contesting everything and thinking
          about nothing at all. The full system recovers that and adds{' '}
          {metrics.economics.rule_vs_best_constant} over the best constant threshold —
          conditional on a {metrics.economics.cost} contest cost, which is a merchant
          input and sits at the cheap end of the curve where the rule is worth least.
        </p>
        <p className="note">
          False-positive cost is disputes contested and lost, times the contest cost.
          It is reported rather than optimised: each wasted contest costs{' '}
          {metrics.economics.cost} while each recovered dispute is worth thousands, so
          minimising it is the wrong objective here. The precision and recall pair for
          the expected-cost rule is omitted deliberately — its threshold is{' '}
          <code>C/A</code> and moves with every dispute, so a single pair would report
          the average of ten operating points as though it were one.
        </p>
      </section>

      <p className="provenance">
        <b>What is real here.</b> The twelve cases below went through the real agent
        mesh and the real evidence engine — nothing on any screen is mocked. The
        figures above are measured on the held-out test split by{' '}
        <code>make eval</code>, seed {metrics.provenance.seed}. The disputes
        themselves are <b>synthetic</b>, generated by a seeded, bit-reproducible
        corpus builder: the architecture is production-shaped, the numbers are not
        production-validated, and what transfers is the ordering of the policies
        rather than the absolute rupees.
      </p>

      <section className="chips" aria-label="Fixture set composition">
        <span className="chip">{breakdown.total} cases</span>
        <span className="chip good">{breakdown.contest} contest</span>
        <span className="chip loss">{breakdown.accept} accept</span>
        <span className="chip warn">{breakdown.blocked} package blocked</span>
        <span className="chip info">{breakdown.routed} routed to a human</span>
        <span className="chip warn">{breakdown.degraded} decided on partial evidence</span>
        <span className="chip-note">
          Chosen to include the cases a console usually hides. The exception list is
          the product.
        </span>
      </section>

      <section className="queue" aria-label="Open cases">
        <table className="cases">
          <thead>
            <tr>
              <th>Dispute</th>
              <th>Reason code</th>
              <th className="n">Amount</th>
              <th>Decision</th>
              <th className="n">P(win) · break-even</th>
              <th>Deadline</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map(({ c, i }) => {
              const d = c.deadline
              const colour = urgencyColour(d.total_hours, d.elapsed)
              const r = c.recommendation
              return (
                <tr
                  key={c.dispute_id}
                  tabIndex={0}
                  onClick={() => onOpenCase(i)}
                  onKeyDown={(e) => e.key === 'Enter' && onOpenCase(i)}
                  aria-label={`${c.reason_code}, ${c.amount}, ${d.display} remaining, ${r.action}`}
                >
                  <td className="n id">{c.dispute_id}</td>
                  <td>
                    <span className="code">{c.reason_code}</span>
                    <span className="title">{c.title}</span>
                  </td>
                  <td className="n amount">{c.amount}</td>
                  <td>
                    <span className={`verdict-tag ${r.action}`}>{r.action}</span>
                  </td>
                  <td className="n">
                    {r.p_win.toFixed(2)}
                    <span className="vs">vs</span>
                    {r.break_even.toFixed(3)}
                  </td>
                  <td>
                    <span className="n countdown" style={{ color: colour }}>{d.display}</span>
                    {/* Length is time left against this code's own filing window,
                        hue is proximity. Seven days half gone is not twenty-one
                        days half gone, and a bare countdown cannot say so. */}
                    <span className="bar">
                      <i style={{ width: `${Math.max(2, (1 - d.elapsed) * 100)}%`, background: colour }} />
                    </span>
                    <span className="bar money">
                      <i style={{ width: `${Math.max(1, (c.amount_minor / maxAmount) * 100)}%` }} />
                    </span>
                  </td>
                  <td><StatusPill c={c} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}
