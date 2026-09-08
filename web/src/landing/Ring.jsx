import React, { useMemo, useRef, useState } from 'react'
import graph from '../graph.json'
import metrics from '../metrics.json'
import { rupees, policy } from './money.js'
import { useCoarsePointer, useInView, useSectionProgress, useReducedMotion, useWebGL2, clamp01 } from './hooks.js'
import RingCanvas from './RingScene.jsx'

/* Act 03 - the chamber, and the overlay that has to stay honest about it.

   The panel says out loud what the network features are worth against the
   decision rule. A showpiece that hides its own contribution is a demo; one
   that states it is an argument. */

const WINDOW = graph.window_days
const FALSE_RING = graph.clusters.find((c) => c.flagged && !c.abusive)

/* Counts at a given day, by binary search over pre-sorted times. Called on
   every scroll frame, so it must not walk 869 entities to move a digit. */
function counterFor(times) {
  const sorted = Float64Array.from(times).sort()
  return (day) => {
    let lo = 0
    let hi = sorted.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (sorted[mid] <= day) lo = mid + 1
      else hi = mid
    }
    return lo
  }
}

const BEATS = [
  {
    lead: 'One merchant, one dispute.',
    body: 'A single merchant sees a device, an address, an instrument — each of them ordinary, each of them attached to one complaint. Nothing in that view is evidence of anything.',
  },
  {
    lead: 'The same entities, across merchants.',
    body: 'Joined on salted hashes at the ingest boundary, the components appear. They are not distinguishable by shape: a fraud ring and a family sharing a card produce the same handful of nodes across the same handful of merchants.',
  },
  {
    lead: 'Tempo is the separating feature.',
    body: `What separates them is rate. ${graph.summary.rings} of ${graph.clusters.length} candidate components cross a threshold that was fitted on the calibration split to hold precision, not to maximise recall — and ${graph.summary.decoys} of those candidates are benign groups built deliberately to sit inside the ring burst-rate range.`,
  },
]

function Readout({ day, entities, edges, resolved }) {
  return (
    <dl className="lp-readout" aria-live="off">
      <div><dt>day</dt><dd className="lp-num">{day.toFixed(1)}<span> / {WINDOW.toFixed(1)}</span></dd></div>
      <div><dt>entities</dt><dd className="lp-num">{entities}<span> / {graph.nodes.length}</span></dd></div>
      <div><dt>shared edges</dt><dd className="lp-num">{edges}<span> / {graph.links.length}</span></dd></div>
      <div><dt>components</dt><dd className="lp-num">{resolved}<span> / {graph.clusters.length}</span></dd></div>
    </dl>
  )
}

/* The fallback is a real view, not an apology: on a machine with no WebGL2 the
   reader gets the components ranked by the feature the detector actually uses,
   with the verdict beside it. */
function Ledger() {
  const rows = useMemo(
    () => [...graph.clusters].sort((a, b) => b.score - a.score).slice(0, 10),
    [],
  )
  return (
    <div className="lp-fallback">
      <table className="lp-ledger">
        <thead>
          <tr>
            <th scope="col">component</th>
            <th scope="col" className="lp-n">members</th>
            <th scope="col" className="lp-n">disputes/day</th>
            <th scope="col" className="lp-n">score</th>
            <th scope="col">verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.i} className={c.flagged && !c.abusive ? 'lp-wrong' : undefined}>
              <td>{c.profile.replace(/_/g, ' ')}</td>
              <td className="lp-n lp-num">{c.members}</td>
              <td className="lp-n lp-num">{c.per_day.toFixed(2)}</td>
              <td className="lp-n lp-num">{c.score.toFixed(3)}</td>
              <td className={c.flagged ? 'lp-tint-blood' : 'lp-tint-indigo'}>
                {c.flagged ? (c.abusive ? 'ring' : 'false ring') : 'cleared'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Panel() {
  const rule = policy(metrics, 'expected_cost_rule')
  return (
    <aside className="lp-ring-panel">
      <h3 className="lp-h3">Detector, held-out split</h3>
      <dl className="lp-kv">
        <div><dt>precision</dt><dd className="lp-num lp-tint-verd">{metrics.rings.precision.toFixed(3)}</dd></div>
        <div><dt>recall</dt><dd className="lp-num">{metrics.rings.recall.toFixed(3)}</dd></div>
        <div><dt>false-ring rate</dt><dd className="lp-num">{metrics.rings.false_ring_rate.toFixed(3)}</dd></div>
        <div><dt>threshold</dt><dd className="lp-num">{metrics.rings.threshold.toFixed(3)}</dd></div>
      </dl>
      <p className="lp-fine">
        Threshold fitted on the calibration split for precision ≥{' '}
        {metrics.rings.precision_floor.toFixed(2)}. Accusing a merchant of
        collusion is not a mistake you make twice, so recall was traded for it:
        {' '}{graph.summary.missed} genuine rings were missed.
      </p>
      <h3 className="lp-h3">The one it got wrong</h3>
      <p className="lp-fine">
        <b className="lp-tint-blood">{FALSE_RING.profile.replace(/_/g, ' ')}</b> —{' '}
        <span className="lp-num">{FALSE_RING.members}</span> entities across{' '}
        <span className="lp-num">{FALSE_RING.merchants}</span> merchants,{' '}
        <span className="lp-num">{FALSE_RING.per_day.toFixed(2)}</span> disputes a day,
        scored <span className="lp-num">{FALSE_RING.score.toFixed(3)}</span> against a
        threshold of <span className="lp-num">{metrics.rings.threshold.toFixed(3)}</span>.
        A device shared legitimately, moving fast enough to look like a farm. One of{' '}
        {metrics.rings.decoys} decoy groups; it is on this page because it is the kind
        of error the product has to own.
      </p>
      <p className="lp-fine lp-fine-rule">
        Honest weight: the network features are worth{' '}
        <b className="lp-num">{rupees(metrics.rings.network_feature_value_minor)}</b> of the{' '}
        <b className="lp-num">{rule.net}</b> the system recovers. This view is not
        justified by that. It exists because the finding is spatial and does not
        survive a table.
      </p>
    </aside>
  )
}

export default function Ring() {
  const reduced = useReducedMotion()
  const webgl2 = useWebGL2()
  const coarse = useCoarsePointer()
  const clock = useRef(reduced ? WINDOW : 0)
  const invalidate = useRef(null)
  const [state, setState] = useState({ day: reduced ? WINDOW : 0, entities: 0, edges: 0, resolved: 0, beat: 0 })

  const nodeCount = useMemo(() => counterFor(graph.nodes.map((n) => n.t)), [])
  const edgeCount = useMemo(() => counterFor(graph.links.map((l) => l.when)), [])
  const resolvedCount = useMemo(() => {
    const last = new Map()
    graph.nodes.forEach((n) => last.set(n.cluster, Math.max(last.get(n.cluster) ?? 0, n.t)))
    return counterFor([...last.values()])
  }, [])

  const [sectionRef] = useSectionProgress((p) => {
    // The sticky stage owns the middle of the section: the clock runs while the
    // scene is pinned, and holds at both ends so the reader can arrive and leave
    // without the graph snapping.
    const run = clamp01((p - 0.16) / 0.62)
    const day = reduced ? WINDOW : run * WINDOW
    clock.current = day
    invalidate.current?.()
    setState((prev) => {
      const next = {
        day,
        entities: nodeCount(day),
        edges: edgeCount(day),
        resolved: resolvedCount(day),
        beat: run < 0.28 ? 0 : run < 0.68 ? 1 : 2,
      }
      // Digits only, so this is a handful of renders across the whole act
      // rather than one per scroll frame.
      return prev.entities === next.entities && prev.edges === next.edges
        && prev.resolved === next.resolved && prev.beat === next.beat
        && Math.abs(prev.day - next.day) < 0.05
        ? prev
        : next
    })
  })

  const [stickyRef, active] = useInView({ threshold: 0.1, once: false })

  return (
    <>
    <section className="lp-act lp-act-ring" id="act-ring" ref={sectionRef}>
      <div className="lp-ring-sticky" ref={stickyRef}>
        <div className="lp-ring-gl">
          {webgl2 ? (
            <RingCanvas
              clock={clock}
              active={active}
              reduced={reduced}
              interactive={!coarse}
              onInvalidate={invalidate}
            />
          ) : (
            <div className="lp-ring-noglm">
              <Ledger />
            </div>
          )}
        </div>

        <div className="lp-ring-ui">
          <header className="lp-ring-head">
            <p className="lp-index">03 <span>The ring</span></p>
            <h2 className="lp-h2 lp-h2-s">
              Shape does not separate a ring from a household.
              <em> Tempo does.</em>
            </h2>
            <div className="lp-beats">
              {BEATS.map((b, i) => (
                <p key={b.lead} className={`lp-beat${state.beat === i ? ' lp-beat-on' : ''}`}>
                  <b>{b.lead}</b> {b.body}
                </p>
              ))}
            </div>
            <Readout {...state} />
          </header>

          <Panel />

          {webgl2 && !reduced && (
            <p className="lp-hint" aria-hidden="true">
              {coarse ? 'scroll advances the window' : 'drag to orbit · scroll advances the window'}
            </p>
          )}
        </div>
      </div>

    </section>

    {/* Below the breakpoint where the overlay panel is dropped, the same panel
        returns in normal flow AFTER the pinned stage - inside it, a fixed-height
        section would lay it over the graph it is describing. The measured
        numbers and the one the detector got wrong are not desktop garnish, and a
        narrow screen is not a reason to show the showpiece without the honesty
        beside it. */}
    <div className="lp-ring-tail">
      <Panel />
    </div>
    </>
  )
}
