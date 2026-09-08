/* Rupees, on the one surface that has to do arithmetic on them.

   The console formats no money in JavaScript at all: every amount arrives from
   Python already grouped, because a second implementation of Indian digit
   grouping is a second thing that can disagree with the ledger. That rule is
   kept here too - every headline figure on this page is a pre-rendered string
   out of metrics.json.

   The exception is a difference between two published figures (an ablation
   delta, or how far the naive classifier falls short of contesting everything).
   Those have no pre-rendered string, and rounding them by hand would be exactly
   the invented number this page must not contain. So they are derived from the
   minor-unit integers that metrics.json does publish, through the platform's
   own en-IN grouping rather than a hand-rolled lakh/crore splitter.

   Verified rather than assumed: this function reproduces every pre-rendered
   `net` string in metrics.json character for character, including
   `rule_vs_best_constant` = the delta ₹2,93,001. If it ever stops doing so, the
   figures on this page have drifted from the ledger and the drift is visible
   the moment the two are read side by side. */

const GROUP = new Intl.NumberFormat('en-IN')

export const rupees = (minor) => `₹${GROUP.format(Math.round(minor / 100))}`

/* Lakh, for an axis label or an annotation where the full figure is already on
   screen beside it and repeating all eight digits costs more than it says. */
export const lakh = (minor) => `₹${(minor / 10000000).toFixed(1)}L`

export const pct = (v, digits = 1) => `${(v * 100).toFixed(digits)}%`

export const policy = (metrics, key) =>
  metrics.economics.policies.find((p) => p.key === key)
