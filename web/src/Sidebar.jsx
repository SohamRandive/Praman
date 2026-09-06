import React from 'react'
import { agentHealth } from './format.js'

/* Persistent chrome. Dark because it is navigated by muscle memory rather than
   read, so it should recede behind the document surface that is being read.

   The status panel is wired to real state - per-agent health rolled up across
   the loaded cases from CaseFile.agent_results - and it reports the gaps as
   loudly as the health. A panel that only ever shows green is decoration. */

const NAV = [
  ['queue', 'Case Queue', 'Twelve decided disputes'],
  ['chamber', 'Network Chamber', 'Entity graph, test split'],
  ['audit', 'Audit Trail', 'Hash-chained, verifiable'],
]

function StatusDot({ status }) {
  return <span className={`dot ${status}`} aria-hidden="true" />
}

export default function Sidebar({ view, onNavigate, cases, metrics }) {
  const health = agentHealth(cases)
  const notOk = health.filter((h) => h.status !== 'ok')
  const drafts = cases.map((c) => c.draft).filter(Boolean)
  const contested = cases.filter((c) => c.recommendation.action === 'contest').length
  const drafted = drafts.filter((d) => !d.blocked).length
  const stripped = drafts.reduce((n, d) => n + d.stripped.length, 0)

  return (
    <nav className="rail" aria-label="Praman console">
      <div className="rail-brand">
        <h1>Praman</h1>
        <p className="rail-sub">Razorpay AI Buildathon 2026 · Track 02</p>
      </div>

      <ul className="rail-nav">
        {NAV.map(([key, label, hint]) => (
          <li key={key}>
            <button
              className={`rail-link${view === key ? ' active' : ''}`}
              onClick={() => onNavigate(key)}
              aria-current={view === key ? 'page' : undefined}
            >
              <span className="rail-link-label">{label}</span>
              <span className="rail-link-hint">{hint}</span>
            </button>
          </li>
        ))}
      </ul>

      <section className="rail-panel" aria-label="System status">
        <h2 className="rail-h">Agent mesh</h2>
        <p className="rail-note">
          Rolled up across {cases.length} loaded cases. Worst observed state wins —
          five sources averaged into one green dot is the silent degradation this
          system exists to refuse.
        </p>
        <ul className="rail-agents">
          {health.map((h) => (
            <li key={h.name} className={h.status}>
              <StatusDot status={h.status} />
              <span className="ra-name">{h.label}</span>
              <span className="ra-count n">
                {h.status === 'ok'
                  ? `${h.ok}/${h.total} ok`
                  : h.down
                    ? `${h.down}/${h.total} down`
                    : `${h.degraded}/${h.total} degraded`}
              </span>
            </li>
          ))}
        </ul>
        {notOk.length > 0 && (
          <p className="rail-flag">
            {notOk.map((h) => `${h.label}: ${h.errors[0] || h.status}`).join(' · ')}.
            Every one of those cases still reached a decision.
          </p>
        )}
      </section>

      <section className="rail-panel" aria-label="Integrity and model status">
        <h2 className="rail-h">Chain and model</h2>
        <ul className="rail-agents">
          <li className="ok">
            <StatusDot status="ok" />
            <span className="ra-name">Audit chain</span>
            <span className="ra-count n">verify on demand</span>
          </li>
          <li className="ok">
            <StatusDot status="ok" />
            <span className="ra-name">Drafting model</span>
            <span className="ra-count n">{drafted}/{contested} contested</span>
          </li>
          <li className="ok">
            <StatusDot status="ok" />
            <span className="ra-name">Grounding verifier</span>
            <span className="ra-count n">{stripped} stripped</span>
          </li>
        </ul>
        <p className="rail-note">
          Prose is drafted only on the contest path, only after the decision, and
          every sentence is re-checked against the artifacts it cites before it
          reaches a payload. The model holds no tools, no retrieval and no write
          authority, and <code>action</code> is hard-coded to <code>draft</code> in
          all 35 reason codes.
        </p>
      </section>

      <section className="rail-scope" aria-label="Defense-only declaration">
        <h2 className="rail-h">Defense only</h2>
        <p>
          It operates on one side of one problem: a merchant who is about to lose
          money, either by failing to respond before <code>respond_by</code> or by
          responding with documents that do not satisfy the code that was raised.
          It has no capability directed at cardholders, at issuers, at other
          merchants, or at fraud-detection systems, and it is designed so that it
          can recommend <em>accepting</em> a dispute — a system that can only ever
          say “fight” is a sales tool, not a risk tool.
        </p>
        <p>
          Detection is one-directional: the system identifies coordinated abuse,
          and exposes no surface for evading detection, probing cards, enumerating
          BINs, or generating adversarial inputs against a fraud model.
        </p>
        <p className="rail-cite">SCOPE.md, quoted verbatim</p>
      </section>

      <p className="rail-foot n">
        seed {metrics.provenance.seed} · {metrics.economics.test_disputes.toLocaleString('en-IN')} held-out disputes
      </p>
    </nav>
  )
}
