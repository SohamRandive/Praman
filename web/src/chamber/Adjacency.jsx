import React, { useMemo, useState } from 'react'

/* The 2D fallback exists for three separate reasons: prefers-reduced-motion, a
   weak or absent GPU, and the plain fact that some people read a flat layout
   faster. It carries the SAME selection model and the same semantics as the
   chamber, and for ranking clusters by burst rate it is genuinely the better
   view - which is why it is a sorted, sortable table and not a placeholder. */

const COLS = [
  ['profile', 'profile', false],
  ['score', 'cohesion', true],
  ['per_day', 'burst/day', true],
  ['members', 'members', true],
  ['disputes', 'disputes', true],
  ['merchants', 'merchants', true],
  ['days', 'window', true],
]

export default function Adjacency({ graph, cluster, day, onSelect, reason }) {
  const [sort, setSort] = useState('score')
  const [asc, setAsc] = useState(false)

  const rows = useMemo(() => {
    const visible = new Set(
      graph.links.filter((l) => l.when <= day).map((l) => l.cluster),
    )
    return graph.clusters
      .filter((c) => visible.has(c.i))
      .slice()
      .sort((a, b) => (asc ? 1 : -1) * (
        typeof a[sort] === 'string' ? String(a[sort]).localeCompare(String(b[sort]))
                                    : a[sort] - b[sort]))
  }, [graph, day, sort, asc])

  return (
    <div className="adjacency">
      <p className="note" style={{ margin: '0 0 10px' }}>
        Flat adjacency view — {reason}. Same data, same selection, same verdicts.
        Sorted by cohesion, it ranks clusters faster than the 3D view does;
        the 3D view is better at showing that ring and decoy clusters occupy the
        same structural space. {rows.length} of {graph.clusters.length} clusters
        have formed by day {day.toFixed(0)}.
      </p>
      <div className="adj-scroll">
        <table className="adj">
          <thead>
            <tr>
              <th>verdict</th>
              {COLS.map(([key, label, numeric]) => (
                <th
                  key={key}
                  className={numeric ? 'n' : ''}
                  onClick={() => { setSort(key); setAsc(sort === key ? !asc : false) }}
                >
                  {label}{sort === key ? (asc ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
              <th>truth</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={c.i}
                className={`${c.i === cluster ? 'sel ' : ''}${c.correct ? '' : 'wrong'}`}
                onClick={() => onSelect({ cluster: c.i })}
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && onSelect({ cluster: c.i })}
              >
                <td className={c.flagged ? 'flag' : 'clear'}>
                  {c.flagged ? 'flagged' : 'cleared'}
                </td>
                <td>{c.profile || '—'}</td>
                <td className="n">{c.score.toFixed(3)}</td>
                <td className="n">{c.per_day.toFixed(2)}</td>
                <td className="n">{c.members}</td>
                <td className="n">{c.disputes}</td>
                <td className="n">{c.merchants}</td>
                <td className="n">{c.days.toFixed(0)}d</td>
                <td className={c.abusive ? 'flag' : 'clear'}>
                  {c.abusive ? 'ring' : 'decoy'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        Rows where the verdict and the truth disagree are marked. Burst rate is
        the column that actually separates the two classes — sort by it and the
        overlap is visible: the slowest rings sit among the fastest households,
        which is exactly where precision dies.
      </p>
    </div>
  )
}
