import React from 'react'
import metrics from './metrics.json'
import { AGENTS, pct, urgencyColour } from './format.js'

/* One case, in five parts: verdict, investigation trace, evidence, network,
   drafted narrative.

   The evidence part still renders `make trace`'s five stages - resolve, bind,
   score, constrain, assemble - because that is the content model and inventing a
   second information architecture for the same facts is how two screens start
   disagreeing. What changed in the shell is the frame around it, not the trace. */

/* The only money formatting in the frontend, and it exists because metrics.json
   carries this one figure in paise. Indian digit grouping, never abbreviated:
   a merchant reads 8,176, and "8.2k" is not a number anyone can reconcile. */
function rupees(minor) {
  const n = String(Math.round(Math.abs(minor) / 100))
  const sign = minor < 0 ? '-' : ''
  if (n.length <= 3) return `${sign}₹${n}`
  const tail = n.slice(-3)
  let head = n.slice(0, -3)
  const parts = []
  while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2) }
  if (head) parts.unshift(head)
  return `${sign}₹${parts.join(',')},${tail}`
}

/* ------------------------------------------------------------------- header */

function DeadlineDial({ d }) {
  const R = 54
  const C = 2 * Math.PI * R
  const left = Math.max(0, 1 - d.elapsed)
  const colour = urgencyColour(d.total_hours, d.elapsed)
  return (
    <div className="dial">
      <svg viewBox="0 0 124 124" width="124" height="124" aria-hidden="true">
        <circle cx="62" cy="62" r={R} fill="none" stroke="var(--rule)" strokeWidth="5" />
        <circle
          cx="62" cy="62" r={R} fill="none" stroke={colour} strokeWidth="5"
          strokeLinecap="butt" strokeDasharray={`${C * left} ${C}`}
        />
      </svg>
      <div className="face">
        <div className="big" style={{ color: colour }}>{d.display}</div>
        <div className="of">of {(d.window_hours / 24).toFixed(0)}d window</div>
      </div>
    </div>
  )
}

function CaseHeader({ c, onBack }) {
  return (
    <header className="case-head">
      <button className="crumb" onClick={onBack}>← Case queue</button>
      <div className="case-title">
        <div>
          <div className="n case-id">{c.dispute_id}</div>
          <h2>
            {c.reason_code} · {c.title}
            {c.resolved_code !== c.reason_code && (
              <em> → resolved to {c.resolved_code}</em>
            )}
          </h2>
          <p className="screen-sub">
            {c.network} · {c.phase.replace(/_/g, ' ')} · {c.merchant_id} ·{' '}
            {c.merchant_archetype?.replace(/_/g, ' ')}
          </p>
        </div>
        <div className="case-figures">
          <div>
            <div className="n amt-big">{c.amount}</div>
            <div className="lbl">debited, held</div>
          </div>
          <DeadlineDial d={c.deadline} />
        </div>
      </div>
      <p className="clock-note">
        The countdown runs against a fixed demo clock derived from the dispute id,
        so the queue reads as twelve cases at different points in their filing
        windows rather than twelve fresh ones. Nothing in the decision path reads it.
      </p>
    </header>
  )
}

/* ------------------------------------------------------------- exceptions --
   Written before the happy path. These are the cases the product exists for. */

function Exceptions({ c }) {
  const e = c.evidence
  const out = []

  /* The entire product thesis on one card: the document exists, the merchant
     believes the package is complete, and a published rule refuses it. */
  const refusal = c.rejections.find((r) => r.constraint_id === 'email_channel_only')
  if (refusal) {
    const rule = c.constraints.find((x) => x.id === 'email_channel_only')
    out.push(
      <div className="exc refused" key="refused">
        <div className="kicker">Document present · does not qualify</div>
        <div className="what">
          The {refusal.label} on file is a WhatsApp thread, and {c.reason_code} does
          not accept one.
        </div>
        {rule && <div className="quote">{rule.message}</div>}
        <div className="swap">
          <span className="from">whatsapp thread</span>
          <span>→</span>
          <span className="to">email thread</span>
          <span className="k">same facts, opposite outcome</span>
        </div>
        <div className="do">
          {rule?.remedy || 'Supply the email thread with the cardholder, or accept.'}
        </div>
      </div>,
    )
  }

  /* Worth less than the cost of fighting it. Arithmetic, not evidence - no
     document and no model can change this one, so it reads calm, not alarmed. */
  if (c.below_cost) {
    out.push(
      <div className="exc below" key="below">
        <div className="kicker">Below the cost of contesting</div>
        <div className="what">
          {c.amount} disputed against {c.contest_cost} to contest.
        </div>
        <div className="do">
          Break-even would need P(win) above {c.recommendation.break_even.toFixed(2)},
          which is not reachable. This is arithmetic, not a judgement about the
          evidence — no document could make this dispute worth fighting.
        </div>
      </div>,
    )
  }

  /* A judgement the system declines to make. Not a loss. */
  if (e.routing === 'route_to_human') {
    out.push(
      <div className="exc routed" key="routed">
        <div className="kicker">Routed to a human</div>
        <div className="what">
          {c.reason_code} does not name the sub-claim, and the classifier fell below
          its confidence floor.
        </div>
        <div className="do">
          The system declines to guess which evidence this case actually requires. A
          person picks the sibling code and the package re-resolves.
        </div>
      </div>,
    )
  }

  const missing = e.gaps.filter((g) => {
    const name = typeof g === 'string' ? g : g.name
    return !name.includes('does not qualify')
  })
  missing.forEach((g, i) => {
    const name = typeof g === 'string' ? g : g.name
    const remedy = typeof g === 'string' ? '' : g.remedy
    out.push(
      <div className="exc" key={`gap${i}`}>
        <div className="kicker">
          {name.includes('source unavailable')
            ? 'Source did not answer'
            : 'Required document missing'}
        </div>
        <div className="what">{name}</div>
        {remedy && <div className="do">{remedy}</div>}
      </div>,
    )
  })

  return out.length ? <>{out}</> : null
}

/* --------------------------------------------------------- 1. the verdict */

function Verdict({ c }) {
  const r = c.recommendation
  return (
    <section className={`card verdict-card ${r.action}`}>
      <div className="card-head">
        <span className="card-n">1</span>
        <h3>Verdict</h3>
        <span className="card-note">deterministic · <code>p &gt; C/A</code> in Python</span>
      </div>
      <div className={`verdict ${r.action}`}>
        {r.action === 'contest' ? 'Contest' : 'Accept'}
      </div>
      <div className="nums">
        <div>
          P(win)
          <b className={r.p_win > r.break_even ? 'win' : ''}>{r.p_win.toFixed(2)}</b>
        </div>
        <div>
          break-even C/A
          <b className={r.p_win > r.break_even ? '' : 'lose'}>{r.break_even.toFixed(3)}</b>
        </div>
        <div>expected value<b>{r.expected_value}</b></div>
        <div>contest cost<b>{c.contest_cost}</b></div>
        {r.comparable && (
          <div>comparable<b>{r.comparable[0]}/{r.comparable[1]}</b></div>
        )}
      </div>
      <p className="rationale">{r.rationale}</p>
      <p className="note">
        Every number above is templated from the decision inputs. Nothing here was
        written by a language model, and contest versus accept is the inequality{' '}
        <code>p &gt; C/A</code> evaluated in Python. The probability is never shown
        without the threshold it is compared against.
      </p>
      <Exceptions c={c} />
    </section>
  )
}

/* --------------------------------------------- 2. the investigation trace */

function Trace({ c }) {
  const degraded = c.agents.filter((a) => a.status !== 'ok')
  return (
    <section className="card">
      <div className="card-head">
        <span className="card-n">2</span>
        <h3>Investigation trace</h3>
        <span className="card-note">five sources, concurrent, deadline-budgeted</span>
      </div>
      <ol className="trace">
        {AGENTS.map(([name, label, bound], i) => {
          const a = c.agents.find((x) => x.name === name)
          const status = a ? a.status : 'missing'
          return (
            <li key={name} className={status}>
              <span className="t-n n">{i + 1}</span>
              <span className="t-body">
                <span className="t-name">{label}</span>
                <span className="t-bound">{bound}</span>
                {a?.errors?.length > 0 && <span className="t-err">{a.errors[0]}</span>}
              </span>
              <span className={`pill ${status}`}>{status}</span>
              <span className="t-conf n">
                {a ? `confidence ${a.confidence.toFixed(2)}` : '—'}
              </span>
            </li>
          )
        })}
      </ol>
      {degraded.length > 0 ? (
        <div className="degraded-banner">
          <b>Decided on partial evidence.</b>{' '}
          {degraded
            .map((a) => `${a.name} ${a.status}${a.errors.length ? ` — ${a.errors[0]}` : ''}`)
            .join('; ')}
          . The confidence band was widened in proportion to what was lost. This
          banner is not dismissible: a decision built on fewer sources must say so.
        </div>
      ) : (
        <p className="note">
          All five sources returned. Partial failure is the default path rather than
          an error path — <code>test_decision_survives_each_agent_failure</code> kills
          each agent in turn and asserts a decision still lands.
        </p>
      )}
    </section>
  )
}

/* ------------------------------------------------- 3. the evidence package */

function Evidence({ c }) {
  const e = c.evidence
  const req = e.checklist.filter((f) => f.required)
  const sup = e.checklist.filter((f) => !f.required)
  const firing = c.constraints.filter((x) => x.status !== 'not_applicable')

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-n">3</span>
        <h3>Evidence package</h3>
        <span className="card-note">resolve · bind · score · constrain</span>
      </div>

      <p className="prose">
        <b>Resolve.</b> {c.reason_code} requires{' '}
        <b>{req.map((f) => f.label).join(', ') || 'no specific document'}</b>
        {sup.length > 0 && <>, supported by {sup.map((f) => f.label).join(', ')}</>}. A
        dictionary lookup against the published matrix — no model in this path.
      </p>
      {e.resolution_note && <p className="note">{e.resolution_note}</p>}

      <div className="sub-h">
        Bind <span className="n">{e.required_met} of {e.required_total} required</span>
      </div>
      <ul className="checklist">
        {e.checklist.map((f) => (
          <li className="check" key={f.field}>
            <span className={`mark ${f.present ? 'yes' : f.required ? 'no' : 'opt'}`}>
              {f.present ? '[x]' : '[ ]'}
            </span>
            <span className="name">{f.label}</span>
            {f.unavailable ? (
              <span className="tag gone">source down</span>
            ) : (
              <span className={`tag${f.required ? ' req' : ''}`}>
                {f.required ? 'required' : 'supporting'}
              </span>
            )}
          </li>
        ))}
        {c.rejections.map((r) => (
          <li className="check" key={`rej-${r.field}`}>
            <span className="mark no">[!]</span>
            <span className="name">{r.label}</span>
            <span className="tag gone">refused · {r.constraint_id}</span>
          </li>
        ))}
      </ul>

      <div className="score-line">
        <span className="item">
          <span className="k">completeness</span>
          <span className="val n">{e.completeness.toFixed(2)}</span>
        </span>
        <span className="item">
          <span className="k">required coverage</span>
          <span className="val n">{pct(e.required_coverage)}</span>
        </span>
        <span className="item">
          <span className="k">package</span>
          <span className={`word ${e.sufficient ? 'good' : 'loss'}`}>
            {e.sufficient ? 'sufficient' : e.routing.replace(/_/g, ' ')}
          </span>
        </span>
      </div>

      <div className="sub-h">Constrain</div>
      {!c.constraints.length ? (
        <p className="con-quiet">{c.reason_code} carries no constraints.</p>
      ) : !firing.length ? (
        <p className="con-quiet">
          <b>{c.constraints.length}</b>{' '}
          {c.constraints.length === 1 ? 'rule' : 'rules'} evaluated, none applicable:{' '}
          {c.constraints.map((x) => x.id).join(', ')}.
        </p>
      ) : (
        <>
          {firing.map((x) => (
            <div className="con" key={x.id}>
              <span className={`st ${x.status}`}>{x.status.replace(/_/g, ' ')}</span>
              <span className="cid">{x.id}</span>
              <span className={`src ${x.source}`}>
                {x.source === 'published' ? 'published' : 'ours'}
              </span>
            </div>
          ))}
          <p className="note">
            <b>published</b> is a documented requirement; <b>ours</b> is our
            formalisation. The required/supporting split is our judgement throughout,
            so the distinction is shown rather than implied. Predicates are
            structured, never evaluated strings.
          </p>
        </>
      )}
    </section>
  )
}

/* --------------------------------------------------------- 4. the network */

function Network({ c, onOpenChamber }) {
  const n = c.network_finding
  // Read, never typed. A hard-coded rupee figure in a component is a number that
  // goes stale the next time `make eval` runs and says nothing when it does.
  const worth = rupees(metrics.rings.network_feature_value_minor)
  const rule = metrics.economics.rule_vs_best_constant
  return (
    <section className="card">
      <div className="card-head">
        <span className="card-n">4</span>
        <h3>Network</h3>
        <span className="card-note">connected components, point-in-time</span>
      </div>
      {n.shares_entity ? (
        <>
          <div className="net-figs">
            <div><b className="n">{n.component_size}</b><span>identities in the cluster</span></div>
            <div><b className="n">{n.prior_merchants}</b><span>merchants already hit</span></div>
            <div><b className="n">{n.prior_disputes}</b><span>prior disputes</span></div>
            <div><b className="n">{n.disputes_per_day.toFixed(2)}</b><span>disputes per day</span></div>
          </div>
          <p className="prose">
            {n.disputes_per_day >= 1
              ? 'Burst rate is consistent with a coordinated cluster. Structure alone does not say this — a household shares entities too — so the claim rests on tempo.'
              : 'Shared entities at household tempo. Not a ring on this evidence: structure is identical between a family and a farm, and only burst rate separates them.'}
          </p>
        </>
      ) : (
        <p className="prose">
          No shared entities with any other claimant. Nothing to exhibit, which is
          the ordinary case — the network finding is a secondary capability worth{' '}
          {worth} against the decision rule’s {rule}.
        </p>
      )}
      <div className="actions">
        <button className="ghost" onClick={onOpenChamber}>Open network chamber →</button>
      </div>
    </section>
  )
}

/* ------------------------------------------------------- 5. the narrative */

/* Each sentence carries its citations, and each citation carries the value the
   cited field actually holds. That is the grounding made legible: a reader can
   check the sentence against the document rather than trusting that someone
   did. Collapsed by default - the prose is the point, the citations are the
   audit. */
function ClaimLine({ claim }) {
  const [open, setOpen] = React.useState(false)
  return (
    <li className={`claim${claim.required ? ' req' : ''}`}>
      <button className="claim-text" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{claim.text}</span>
        <span className="cite-count n">{claim.citations.length} cited</span>
      </button>
      {open && (
        <ul className="cites">
          {claim.citations.map((cite) => (
            <li key={cite.ref}>
              <span className="n ref">{cite.ref}</span>
              <span className="cite-val">{cite.value || '—'}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function Narrative({ c }) {
  const d = c.draft

  /* Nothing is drafted for an accepted dispute: there is no filing to write,
     and generating prose nobody will submit would be the model doing work
     purely to look busy. */
  if (!d) {
    return (
      <section className="card">
        <div className="card-head">
          <span className="card-n">5</span>
          <h3>Representment narrative</h3>
          <span className="card-note">not drafted</span>
        </div>
        <p className="prose">
          This dispute is being accepted, so there is no filing to draft. The
          drafting model runs only on the contest path, and only after the decision
          — prose cannot influence an inequality that was already evaluated.
        </p>
      </section>
    )
  }

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-n">5</span>
        <h3>Representment narrative</h3>
        <span className="card-note">
          drafted, then verified · {pct(d.groundedness)} grounded
        </span>
      </div>

      {d.blocked ? (
        <div className="exc refused">
          <div className="kicker">Draft blocked by the grounding verifier</div>
          <div className="what">{d.block_reason}</div>
          <div className="do">
            Required coverage fell from {pct(d.coverage_before)} to{' '}
            {pct(d.coverage_after)} once ungrounded sentences were stripped. The
            draft is blocked and escalated rather than filed shortened — a
            narrative that reads complete while asserting less than the package
            promised is worse than no narrative.
          </div>
        </div>
      ) : (
        <>
          <p className="drafted">{d.summary}</p>
          <div className="sub-h">
            Claims <span className="n">{d.claims.length}, every one cited</span>
          </div>
          <ul className="claims">
            {d.claims.map((claim) => <ClaimLine key={claim.id} claim={claim} />)}
          </ul>
        </>
      )}

      {d.stripped.length > 0 && (
        <>
          <div className="sub-h">
            Stripped by the verifier <span className="n">{d.stripped.length}</span>
          </div>
          <ul className="claims">
            {d.stripped.map((s, i) => (
              <li className="claim stripped" key={i}>
                <span className="strip-reason">{s.reason.replace(/_/g, ' ')}</span>
                <span className="strip-text">{s.text}</span>
                <span className="strip-why">{s.detail}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="note">
        Every sentence above resolved each of its citations to a field of an
        artifact actually in this package, and every value in its prose appears in
        one of those fields. Anything that did not was stripped before assembly —
        which is why groundedness reads {pct(d.groundedness)} rather than being
        asserted. Drafted by the <code>{d.provider}</code> provider; the model holds
        no tools, no retrieval and no write authority, and never saw the decision.
      </p>

      <div className="sub-h">The <code>contest()</code> body</div>
      <pre className="payload">
        {JSON.stringify(
          {
            amount: c.amount_minor,
            ...Object.fromEntries(
              c.evidence.checklist
                .filter((f) => f.present)
                .map((f) => [f.field, [`doc_${f.field}`]]),
            ),
            summary: c.draft && !c.draft.blocked ? c.draft.summary : '',
            action: 'draft',
          },
          null,
          2,
        )}
      </pre>
      <p className="note">
        <code>action</code> is hard-coded to <code>draft</code> and asserted for all
        35 reason codes. No code path in this system sets <code>submit</code>; a human
        approval does that and writes its own audit record when it does.
      </p>
    </section>
  )
}

/* --------------------------------------------------------------- the case */

export default function CaseDetail({ c, onBack, onOpenChamber, onOpenAudit }) {
  return (
    <div className="screen">
      <CaseHeader c={c} onBack={onBack} />
      <Verdict c={c} />
      <Trace c={c} />
      <Evidence c={c} />
      <Network c={c} onOpenChamber={onOpenChamber} />
      <Narrative c={c} />
      <div className="actions trailing">
        <button className="primary" onClick={onOpenAudit}>
          Audit trail for this case →
        </button>
        <button className="ghost">Request missing document</button>
      </div>
    </div>
  )
}
