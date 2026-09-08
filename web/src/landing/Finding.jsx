import React from 'react'
import metrics from '../metrics.json'
import { rupees, policy } from './money.js'
import { stagger, useCountUp } from './hooks.js'

/* Act 02 - the finding, and the most interesting thing the project has to say.

   The ordering is the argument: contesting everything, which requires no model
   at all, beats a competent classifier thresholded at 0.5 by a wide margin. A
   page that led with "our model nets Rs 94L" would be hiding that, and the
   ablation underneath would be measuring the weakness of a straw man.

   Every figure is a pre-rendered string from metrics.json, with two exceptions
   that are differences between published figures and are computed here from the
   minor-unit integers rather than typed by hand. */

const ORDER = ['accept_all', 'naive_half', 'contest_all', 'best_constant', 'expected_cost_rule']
const TONE = {
  accept_all: 'ink',
  naive_half: 'blood',
  contest_all: 'indigo',
  best_constant: 'ochre',
  expected_cost_rule: 'verd',
}
const NOTE = {
  accept_all: 'concede every dispute — the floor any policy has to clear',
  naive_half: 'a competent classifier, thresholded where everyone thresholds it',
  contest_all: 'no model, no features, no threshold — a constant rule at t = 0',
  best_constant: 'the same model, at the best constant threshold money can buy',
  expected_cost_rule: 'contest when p > C/A — the threshold moves with the amount',
}

function Bar({ p, max, live, index }) {
  const value = useCountUp(p.net_minor, live, { duration: 1700, delay: 200 + index * 130 })
  const share = p.net_minor / max
  return (
    <li
      className={`lp-bar lp-rv lp-tone-${TONE[p.key]}`}
      style={{ ...stagger(index, 110), '--lp-scale': share }}
    >
      <div className="lp-bar-head">
        <span className="lp-bar-label">{p.label}</span>
        <span className="lp-bar-value lp-num">{rupees(value)}</span>
      </div>
      <div className="lp-bar-track">
        <span className="lp-bar-fill" />
      </div>
      <p className="lp-bar-note">{NOTE[p.key]}</p>
    </li>
  )
}

export default function Finding({ live }) {
  const policies = ORDER.map((k) => policy(metrics, k))
  const max = Math.max(...policies.map((p) => p.net_minor))
  const contestAll = policy(metrics, 'contest_all')
  const naive = policy(metrics, 'naive_half')
  const rule = policy(metrics, 'expected_cost_rule')
  const best = policy(metrics, 'best_constant')

  // Both derived from published minor-unit figures, never typed as literals.
  const naiveShortfall = contestAll.net_minor - naive.net_minor
  const overTrivial = (rule.net_minor / contestAll.net_minor - 1) * 100

  return (
    <section className="lp-act lp-act-finding" id="act-finding">
      <div className="lp-act-head">
        <p className="lp-index lp-rv" style={stagger(0)}>02 <span>The finding</span></p>
        <h2 className="lp-h2 lp-display-2 lp-rv" style={stagger(1)}>
          The trivial policy beats
          <em> the machine-learning policy.</em>
        </h2>
        <p className="lp-lede lp-lede-2 lp-rv" style={stagger(2)}>
          Contesting every dispute nets <b className="lp-num">{contestAll.net}</b> and requires
          no model whatsoever. The same features, thresholded at the customary p &gt; 0.5,
          net <b className="lp-num">{naive.net}</b> — <b className="lp-num">{rupees(naiveShortfall)}</b>{' '}
          worse than thinking about nothing at all. That result is the reason this page
          exists, and it survived every attempt to make it go away.
        </p>
      </div>

      <ol className="lp-bars">
        <span
          className="lp-marker"
          style={{ left: `${(contestAll.net_minor / max) * 100}%` }}
          aria-hidden="true"
        >
          <span className="lp-marker-label">contest everything</span>
        </span>
        {policies.map((p, i) => (
          <Bar key={p.key} p={p} max={max} live={live} index={i} />
        ))}
      </ol>

      <div className="lp-verdict lp-rv" style={stagger(7)}>
        <p>
          The full system nets <b className="lp-num lp-tint-verd">{rule.net}</b> —{' '}
          <b className="lp-num">{overTrivial.toFixed(1)}%</b> above the policy that thinks
          about nothing. That is the honest size of the win, and it is worth more than a
          bigger number that falls over under questioning.
        </p>
      </div>

      <div className="lp-two lp-two-tight">
        <div className="lp-panel lp-rv" style={stagger(8)}>
          <h3 className="lp-h3">The ablation that was overstated</h3>
          <p className="lp-body lp-body-s">
            Removing the expected-cost rule and falling back to a fixed 0.5 makes the rule
            look worth <b className="lp-num">{metrics.economics.rule_vs_naive_half}</b>. It
            is not. Contest-everything <i>is</i> a constant threshold — t = 0 — so the
            fallback that lacks the mechanism is the <i>best</i> constant, not a bad one.
            Fitted on the calibration split, that constant is{' '}
            <b className="lp-num">t = {metrics.economics.t_star.toFixed(3)}</b>, netting{' '}
            <b className="lp-num">{best.net}</b>.
          </p>
          <p className="lp-body lp-body-s">
            The claim being made is that the threshold should <i>vary with the amount</i>.
            Measured against the strongest alternative that lacks exactly that, it is
            worth <b className="lp-num lp-tint-verd">{metrics.economics.rule_vs_best_constant}</b> —{' '}
            not the number above. An ablation whose fallback is weak measures the weakness
            of the fallback.
          </p>
        </div>

        <div className="lp-panel lp-rv" style={stagger(9)}>
          <h3 className="lp-h3">What each policy pays for being wrong</h3>
          <table className="lp-ledger">
            <thead>
              <tr>
                <th scope="col">policy</th>
                <th scope="col" className="lp-n">contested</th>
                <th scope="col" className="lp-n">false-positive cost</th>
              </tr>
            </thead>
            <tbody>
              {policies.filter((p) => p.key !== 'accept_all').map((p) => (
                <tr key={p.key} className={p.key === 'expected_cost_rule' ? 'lp-lead' : undefined}>
                  <td>{p.label}</td>
                  <td className="lp-n lp-num">{(p.contested_share * 100).toFixed(1)}%</td>
                  <td className="lp-n lp-num">{p.false_positive_cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="lp-fine">
            False-positive cost is contest cost spent on disputes that were then lost.
            Contesting everything wins the most cases and burns{' '}
            <b className="lp-num">{contestAll.false_positive_cost}</b> doing it. The rule
            spends <b className="lp-num">{rule.false_positive_cost}</b> and nets more.
          </p>
        </div>
      </div>

      <ul className="lp-chips lp-rv" style={stagger(10)}>
        <li className="lp-chip-card lp-tone-blood">
          <span className="lp-k">PR-AUC, base rate {metrics.model.base_rate.toFixed(3)}</span>
          <b className="lp-num">{metrics.model.pr_auc.toFixed(4)}</b>
          <span className="lp-chip-note">
            misses its {metrics.model.pr_auc_target.toFixed(2)} target. Reported as a miss;
            the target was wrong, not the metric.
          </span>
        </li>
        <li className="lp-chip-card lp-tone-verd">
          <span className="lp-k">calibration error</span>
          <b className="lp-num">{metrics.calibration.ece.toFixed(4)}</b>
          <span className="lp-chip-note">
            inside the {metrics.calibration.ece_target.toFixed(2)} bar. The protocol selected
            no calibrator — the scores were already calibrated, and a fit would have added
            variance.
          </span>
        </li>
        <li className="lp-chip-card lp-tone-indigo">
          <span className="lp-k">ROC-AUC against the corpus ceiling</span>
          <b className="lp-num">
            {metrics.model.roc_auc.toFixed(3)} / {metrics.model.roc_auc_ceiling.toFixed(3)}
          </b>
          <span className="lp-chip-note">
            under the achievable ceiling measured on the corpus itself. Anything above it
            would be a leak, not a result.
          </span>
        </li>
      </ul>
    </section>
  )
}
