/* Display helpers shared by every screen in the shell.

   Money is NEVER formatted here. Amounts arrive from Python already rendered
   with Indian digit grouping - `praman.console.serialize.rupees` for case data,
   the same function for `metrics.json` - because a second implementation of
   digit grouping in JavaScript is a second thing that can disagree with the
   ledger. If a number needs to be shown as rupees, it is formatted upstream. */

export const pct = (n, digits = 0) => `${(n * 100).toFixed(digits)}%`

/* Urgency is a continuous hue, not three buckets: the window closes gradually
   and the colour should too. Verdigris while there is room, ochre as it
   tightens, oxblood at the end. */
export function urgencyColour(remainingHours, elapsed) {
  if (remainingHours <= 24) return 'var(--oxblood)'
  if (remainingHours <= 72 || elapsed > 0.75) return 'var(--ochre)'
  if (elapsed > 0.5) return 'var(--olive)'
  return 'var(--verdigris)'
}

/* The five agents, in dispatch order, with what each one is actually bound by.
   The order is fixed rather than sorted alphabetically so the investigation
   trace reads as a sequence of work rather than as a list of names. */
export const AGENTS = [
  ['evidence', 'Evidence Retrieval', 'I/O — documents from the merchant’s own records'],
  ['network', 'Network Forensics', 'graph — shared entities across merchants'],
  ['precedent', 'Precedent Recall', 'vector — comparable disputes already settled'],
  ['policy', 'Policy & Compliance', 'deterministic — no model in this path'],
  ['merchant', 'Merchant Context', 'SQL — this merchant’s own history'],
]

/* Per-agent health across every loaded case. Counted, never averaged into a
   single green dot: "4 of 12 degraded" is actionable and "92% healthy" is not,
   and a status panel that can only ever report health is decoration. */
export function agentHealth(cases) {
  return AGENTS.map(([name, label, bound]) => {
    const runs = cases.map((c) => c.agents.find((a) => a.name === name)).filter(Boolean)
    const count = (status) => runs.filter((r) => r.status === status).length
    const degraded = count('degraded')
    const down = count('failed') + count('timeout')
    return {
      name,
      label,
      bound,
      total: runs.length,
      ok: count('ok'),
      degraded,
      down,
      // Worst observed state wins. Rolling five sources into one optimistic
      // summary is exactly the silent degradation this product exists to refuse.
      status: down ? 'failed' : degraded ? 'degraded' : 'ok',
      errors: [...new Set(runs.flatMap((r) => r.errors))],
    }
  })
}

/* The fixture set broken down by what the system actually decided. Derived in
   view from cases.json rather than exported, so it cannot drift from the cases
   rendered next to it. */
export function decisionBreakdown(cases) {
  const blocked = cases.filter((c) => c.evidence.routing === 'blocked')
  const routed = cases.filter((c) => c.evidence.routing === 'route_to_human')
  return {
    total: cases.length,
    contest: cases.filter((c) => c.recommendation.action === 'contest').length,
    accept: cases.filter((c) => c.recommendation.action === 'accept').length,
    blocked: blocked.length,
    routed: routed.length,
    degraded: cases.filter((c) => c.agents.some((a) => a.status !== 'ok')).length,
  }
}

export const policy = (metrics, key) =>
  metrics.economics.policies.find((p) => p.key === key)
