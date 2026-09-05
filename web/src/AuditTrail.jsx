import React, { useEffect, useMemo, useState } from 'react'
import { verifyChain } from './hashchain.js'

/* The audit trail, and a verification that is a real check on real data.

   Two rules govern this screen. First, the chain is recomputed in the browser
   from the record bodies rather than being reported intact by the server that
   wrote it - otherwise the integrity claim is exactly as trustworthy as the
   thing it is meant to check. Second, the tamper control is not a demo mode: it
   edits a record in memory and the same verifier that passes on the untouched
   chain fails on the edited one. */

function Records({ records, broken, verified }) {
  return (
    <table className="audit">
      <thead>
        <tr>
          <th>Actor</th>
          <th>Event</th>
          <th className="n">Timestamp</th>
          <th className="n">prev_hash</th>
          <th className="n">record_hash</th>
          <th>Checked</th>
        </tr>
      </thead>
      <tbody>
        {records.map((r, i) => (
          <tr key={i} className={broken.has(i) ? 'broken' : ''}>
            <td className="a">{r.actor}</td>
            <td>{r.event}</td>
            <td className="n ts">{r.ts.slice(11, 19)}</td>
            <td className="n hash">{r.prev_hash.slice(0, 12)}…</td>
            <td className="n hash">{r.record_hash.slice(0, 12)}…</td>
            <td className={broken.has(i) ? 'bad' : verified ? 'ok' : 'hash'}>
              {verified ? (broken.has(i) ? 'BROKEN' : 'verified') : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function AuditTrail({ cases, selected, onSelect }) {
  const c = cases[selected]
  const [records, setRecords] = useState(c.audit)
  const [result, setResult] = useState(null)
  const [sweep, setSweep] = useState(null)

  // Switching case resets both the working copy and any verdict on it: carrying
  // a "verified" badge across to a chain that was never checked would be the
  // exact dishonesty this screen exists to avoid.
  useEffect(() => { setRecords(c.audit); setResult(null) }, [c])

  const totalRecords = useMemo(
    () => cases.reduce((n, x) => n + x.audit.length, 0), [cases])

  const verify = async () => {
    setResult(await verifyChain(records))
    setSweep(null)
  }

  const verifyAll = async () => {
    const failures = []
    for (const x of cases) {
      const problems = await verifyChain(x.audit)
      if (problems.length) failures.push({ id: x.dispute_id, problems })
    }
    setSweep({ chains: cases.length, records: totalRecords, failures })
  }

  const tamper = () => {
    const i = Math.min(2, records.length - 1)
    setRecords(records.map((r, n) =>
      (n === i ? { ...r, event: 'decision.suppressed' } : r)))
    setResult(null)
    setSweep(null)
  }

  const restore = () => { setRecords(c.audit); setResult(null) }
  const broken = new Set((result || []).map((p) => p.i))
  const edited = records !== c.audit

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h2>Audit trail</h2>
          <p className="screen-sub">
            Every step writes an append-only, hash-chained <code>AuditRecord</code> —
            including the failures. {totalRecords} records across {cases.length}{' '}
            cases, each chain rooted at a genesis hash of sixty-four zeroes.
          </p>
        </div>
      </header>

      <section className="card">
        <div className="card-head">
          <h3>Chain</h3>
          <span className="card-note">
            {records.length} records · {c.dispute_id}
          </span>
        </div>

        <div className="case-picker" role="group" aria-label="Case">
          {cases.map((x, i) => (
            <button
              key={x.dispute_id}
              className={`picker${i === selected ? ' active' : ''}`}
              onClick={() => onSelect(i)}
            >
              <span className="n">{x.reason_code}</span>
              <span className="picker-id n">{x.dispute_id.slice(5, 13)}</span>
            </button>
          ))}
        </div>

        <Records records={records} broken={broken} verified={!!result} />

        <div className="actions">
          <button className="primary" onClick={verify}>Verify integrity</button>
          <button className="ghost" onClick={verifyAll}>
            Verify all {cases.length} chains
          </button>
          {edited ? (
            <button className="ghost" onClick={restore}>Restore the original trail</button>
          ) : (
            <button className="danger" onClick={tamper}>Tamper with a record</button>
          )}
        </div>

        {result && (
          <div className={`integrity ${result.length ? 'fail' : 'pass'}`}>
            {result.length === 0 ? (
              <>
                <b>Chain intact.</b> All {records.length} records recomputed in this
                browser: each record’s SHA-256 matches its stored hash, and each
                points at the one before it. The canonical form is byte-identical to
                Python’s <code>json.dumps(sort_keys=True)</code>. Nothing here was
                taken on trust.
              </>
            ) : (
              <>
                <b>Chain broken at record {result[0].i}.</b> {result[0].why}. The
                break is <em>localised</em> — the chain names exactly which record
                was altered rather than reporting a vague failure. What it costs an
                attacker is the repair: recomputing this record’s hash changes the
                next record’s <code>prev_hash</code>, which changes that record’s
                hash, so hiding one edit means rewriting every record after it.
                Detection is local; forgery is not. Restore the trail to put it back.
              </>
            )}
          </div>
        )}

        {sweep && (
          <div className={`integrity ${sweep.failures.length ? 'fail' : 'pass'}`}>
            {sweep.failures.length === 0 ? (
              <>
                <b>All {sweep.chains} chains intact.</b> {sweep.records} records
                recomputed here, from the stored bodies, in this browser. The
                in-memory edit above is deliberately not included — this sweep reads
                the originals.
              </>
            ) : (
              <>
                <b>{sweep.failures.length} of {sweep.chains} chains broken.</b>{' '}
                {sweep.failures.map((f) => f.id).join(', ')}.
              </>
            )}
          </div>
        )}

        <p className="note">
          A record body is <code>ts</code>, <code>actor</code>, <code>event</code>,{' '}
          <code>inputs_hash</code>, <code>outputs_hash</code> and{' '}
          <code>prev_hash</code>. Inputs and outputs are stored as hashes rather than
          contents, so the trail is verifiable without carrying dispute data around
          with it.
        </p>
      </section>
    </div>
  )
}
