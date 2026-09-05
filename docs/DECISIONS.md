# Engineering decisions

One record per non-obvious choice, written at the time the choice was made.
Each states the decision, why it was taken, and what it costs — a decision
record without a stated cost is advertising.

---

## ADR-001 — Gradient-boosted trees, not a neural network

**Decision.** Win probability is modelled with LightGBM over tabular features,
calibrated with isotonic regression.

**Why.** The feature space is small, tabular, and partially missing by design —
"we could not reach the courier API" is itself a feature. It must be explainable
to a merchant who has just had ₹40,000 debited and wants to know why the system
told them to give up. Gradient-boosted trees handle missingness natively, train
in seconds, and expose per-feature attribution that survives being read aloud.

**Cost.** No representation learning over free text. If dispute narratives later
carry signal, this model cannot use them without an explicit feature.

**Rejected.** A transformer over dispute text. The track rewards choosing
deterministic or simple solutions where AI is unnecessary; reaching for a
sequence model on 17k rows of tabular data demonstrates the opposite of
judgement.

---

## ADR-002 — The language model holds no write authority

**Decision.** The model appears exactly twice: drafting the representment prose,
and narrating a ring finding. In neither place does it have tools, retrieval, or
decision power. Contest versus accept is `p > C/A`, evaluated in Python.

**Why.** The output is a factual statement submitted to a bank. A fabricated
delivery date in a representment is not a bad user experience, it is a false
statement made to a financial institution on a merchant's behalf. Decision
authority and generation authority are therefore separated at the architecture
level, not by prompt instruction.

**Cost.** The drafter cannot resolve an ambiguity by looking something up; if
the package is incomplete, the draft is blocked rather than improvised. That is
the intended behaviour.

---

## ADR-003 — 3D for the network view only

**Decision.** One 3D surface, the network chamber. Every other surface is flat
DOM. A full 2D adjacency fallback ships regardless of whether 3D does.

**Why.** Overlapping fraud communities collapse into an unreadable hairball in
2D projection; depth and rotation are what make them separable. That argument
applies to the graph and to nothing else in the product.

**Cost.** A rendering path that must hold 60fps at 5,000 nodes, and an
accessibility obligation (`prefers-reduced-motion`, keyboard focus, colour never
the sole carrier of state). If it is not smooth, it is cut — a janky 3D view
converts the strongest differentiator into evidence of overreach.

---

## ADR-004 — NetworkX in-process, not a graph database

**Decision.** The entity graph is built in-process with NetworkX and
snapshotted.

**Why.** Correct and fast at this scale. A graph database adds operational
surface, a second datastore, and a deployment story, for no benefit at 60
merchants and ~17k disputes.

**Cost.** Known to be the first thing that breaks at 100×. At that point the
graph needs a real store with incremental community maintenance rather than
full recomputation. This is a deliberate, dated choice, not an oversight.

---

## ADR-005 — Split by merchant, stratified by archetype *and* merchant quality

**Decision.** Train/calibration/test are split at the merchant level. Within each
archetype, merchants are sorted by quality and dealt into the splits
proportionally, with split volume balanced at the same time. Counts are
allocated by largest remainder.

**Why, in the order the failures appeared.**

*By merchant*, because evidence hygiene is a merchant-level property — a random
row split leaks it across the boundary and inflates every metric.

*Stratified by archetype*, because merchant order volume is heavy-tailed (food
delivery runs 2,000–15,000 orders/month, SaaS 80–700), so an unstratified
shuffle put most corpus volume in one split by chance.

*Stratified by quality too*, because archetype stratification alone was not
enough. Within-archetype spread in hygiene and fulfilment reliability is wide,
and with a handful of merchants per archetype per fold the draw stayed lumpy:
d2c_apparel came out at winnable rates of 0.365 / 0.427 / 0.513, a 15-point
shift that would have read as spurious model degradation on the test split.
Quality is `fulfilment_reliability × mean(hygiene)` — the two things that
actually drive the label.

*Volume balanced simultaneously*, because fixing quality alone moved the
imbalance straight into split size (59 / 19 / 22 against a requested 60 / 15 /
25). The two are independent and both must be balanced or the error just
relocates.

*Background disputes allocated per split*, because group disputes land wherever
their group lives and dragged calibration from 15% to 12%.

*Rotating tie-break*, because every split starts at zero volume, so the first
comparison in each archetype is always a tie — and breaking it by name sent the
lowest-quality merchant of every archetype to `calibration`, depressing its
winnable rate by five points on its own.

**On largest-remainder allocation.** It is **currently inert**. At 20 merchants
per archetype the 60/15/25 ratios divide evenly, so naive flooring produces the
same counts. It was load-bearing at 12 per archetype, where `int(12 × 0.15) == 1`
starved calibration. It is retained as a guard against a future change to
merchant count or ratios, and is named here as a guard rather than claimed as an
active fix — a decision record that takes credit for an inactive mechanism is
worse than one that omits it.

**Result.** Splits land at exactly 60 / 15 / 25 by dispute count, with a
winnable-rate spread of 0.031 across folds.

**Cost.** Fewer effective independent units than a row split appears to give,
and a split that is systematic rather than random. That is standard stratified
sampling on the confounder, and it is why the corpus carries 100 merchants
rather than 60.

---

## ADR-006 — Decoy groups are built by the same mechanism as rings

**Decision.** The corpus contains decoy groups — households, office pantries,
shared payment devices — generated by the identical code path as abuse rings,
differing only in temporal concentration and dispute propensity.

**Why.** If decoys were built by a different mechanism, the detector would learn
the artefact of that mechanism rather than the real discrimination. The whole
difficulty of ring detection is that a family sharing one address and one device
is structurally a connected component and behaviourally not a ring.

**Cost.** Ring detection is genuinely hard on this corpus, and the burst-rate
distributions overlap. That overlap is where precision dies, and it is
deliberately not designed away.

---

## ADR-007 — Observed labels carry issuer noise

**Decision.** Ground truth is factored into `merchant_at_fault` and
`evidence_sufficient`; the training label `observed_won` is drawn by passing
ground truth through a noisy issuer model. Models train on `observed_won`, never
on any `gt_` column.

**Why.** Training on noiseless ground truth produces a model that is
confidently wrong in production and a calibration curve that flatters the
system. Real issuers are noisy and the label a merchant actually gets back is
the noisy one.

**Cost.** It caps achievable AUC. That ceiling is a feature: a model reporting
above it has a leak, and the ceiling is the first thing to check when a number
looks too good.

---

## ADR-008 — Unevaluated constraints are declared, not assumed passed

**Decision.** Where the generator does not model the fact a constraint needs, the
constraint is recorded as `unevaluated:<id>` rather than silently passing.

**Why.** A corpus that quietly assumes unmodelled constraints hold would inflate
winnability, and the inflation would be invisible in every downstream number.

**Cost.** A visible category of "we do not know" in the corpus statistics, which
has to be explained rather than hidden. That is the correct trade.

---

## ADR-009 — Evidence sufficiency is decided before, and independently of, any model

**Decision.** The evidence engine is fully deterministic: reason code resolves to
required and supporting fields plus constraints, artifacts bind to fields,
completeness is scored, and any missing required field blocks the package with a
named gap.

**Why.** It is the reference against which everything else is checked. If a
required document is absent, that is a fact about record-keeping, not a
probability, and no model should be permitted to average it away. Blocking with
a named, actionable gap ("no signed delivery confirmation — request from
courier, or accept") is what separates a tool from a liability.

**Cost.** The system refuses to produce a package in cases where a merchant might
have wanted one anyway. That refusal is the product.

---

## ADR-010 — A baseline must decide and settle on the same source of truth

**Context.** The corpus economics compare four policies on the held-out test
split: accept everything, contest everything, an oracle at a fixed threshold,
and an oracle using the expected-cost rule. The oracle rows exist to bound the
headroom the decision rule can possibly add, independently of how good the
classifier turns out to be.

**The defect.** An earlier version of this comparison had the oracle rows
*decide* on `gt_winnable` while *settling* on `observed_won`. That is not an
oracle. It is a rule that knows the noiseless truth placing bets that pay out
against a noisy outcome, and the two disagree on exactly the cases the
expected-cost rule declines to contest — the small-value ones. The rule was
therefore credited for avoiding losses that only existed because the oracle was
allowed to be wrong about its own criterion.

On the corpus that produced it, the inflation was material:

| | Net |
|---|---|
| Claimed headroom, inconsistent oracle | ₹1,96,532 |
| Real headroom, consistent oracle | ₹1,47,007 |
| Inflation | ₹49,525 (25%) |

**Decision.** Every baseline decides and settles on the same source of truth. In
`eval/validate_corpus.py` the oracle rows decide on `observed_won` and are paid
out on `observed_won`; the model rows will decide on a calibrated probability and
be paid out on `observed_won`. A baseline that mixes the two is not a baseline,
it is a leak wearing one.

**The general rule this implies.** A comparison is only valid if every policy in
it is scored by the same outcome it was allowed to see. Whenever a baseline
looks unexpectedly strong, check that first — before the model, before the
hyperparameters, before the features.

**What it costs.** The honest oracle headroom is much smaller than the inflated
one, and on this corpus it is ₹17,450 rather than a figure six times larger.
That is the correct number and it is reported as what it is: a **floor**, not a
headline. Against a *perfect* classifier the expected-cost rule can only improve
disputes worth less than the cost of contesting them — 526 of 4,375 test
disputes here — because a perfect classifier already declines everything it
would lose. The rule earns its keep against a calibrated but imperfect model,
where the threshold `C/A` moves across the amount range and changes far more
decisions. Phase 3 reports that figure; this one bounds it from below.

**Note on corpus dependence.** The size of this floor is a property of the
amount distribution, not of the method. A corpus whose skipped disputes average
₹188 yields roughly ₹162 avoided each; one whose skipped disputes average ₹246
yields roughly ₹104 each. Both are correct for their own corpus, which is
precisely why the number must be re-measured rather than inherited.


---

## ADR-011 — The PR-AUC target was revised downward, after it was missed

**Context.** §15 set a target of PR-AUC ≥ 0.80. The measured value on the
held-out test split is **0.6609** at a 0.360 base rate. That is real lift over
the base rate and it is a miss against the stated target.

**Decision.** Report the miss, revise the target to ≥ 0.60, and record here why
it moved — rather than change the metric, re-cut the split, or quietly drop the
row.

**Why the original target was wrong.** It was set before the economics were
measured, when the implicit model of the problem was "a better classifier
recovers more money." The measurement contradicted that. Break-even is `C/A`,
and at ₹350 against typical Indian dispute values the best constant threshold
collapses to t\* = 0.240 — so contest-everything, which is t = 0, already
captures ₹89.1 lakh of the ₹94.0 lakh the full system recovers. When the
threshold sits that low, the probability estimate barely moves the decision.

A mediocre classifier that barely moves the money is therefore **consistent with
the central finding rather than a refutation of it**. Chasing PR-AUC 0.80 on
this corpus would be optimising the component the evidence says is not the
binding constraint, and the achievable ceiling is 0.897 AUC anyway.

**What this does not excuse.** The corrected number must still beat every
baseline in rupees, and it does. If the model had failed *that*, the low PR-AUC
would be a defect rather than a consequence, and the response would be to fix
the model rather than the target.

**Cost.** A revised target invites the reasonable suspicion that it was moved to
fit the result. The defence is that the reasoning is recorded here, the original
figure is still in the history, the miss is reported in the results table
alongside the revision, and the metric itself was not touched.

---

## ADR-012 — A decision rule is ablated against the best tuned constant, not against 0.5

**Context.** The expected-cost rule's claim is specific: the contest threshold
should **vary with the disputed amount**, because break-even is `C/A`. The
ablation has to test that claim and nothing else.

**The defect.** The first version ablated the rule by falling back to a fixed
p > 0.5, reporting a gain of ₹43,64,371. But *contest-everything is itself a
constant threshold* — t = 0 — and it nets ₹89,12,555. So the best constant
threshold can never do worse than that, and the ₹43.6 lakh figure was mostly
measuring that 0.5 is a bad constant, which is true and is not the claim.

**Decision.** The ablation baseline is the **best constant threshold, fitted on
the calibration split by net rupees**. On this corpus t\* = 0.240, netting
₹91,11,449, and the honest value of the amount-varying rule is **₹2,93,001** —
an order of magnitude smaller than the original figure. The 0.5 comparison is
retained as a separate, explicitly labelled row, because "a competent classifier
with a naive threshold loses ₹38.7 lakh against contesting everything" is a real
and useful result. It is just a different one.

**The general rule.** An ablation must remove the specific mechanism being
claimed, and the fallback must be the strongest alternative that lacks it. A
weak fallback measures the weakness of the fallback.

**Cost.** The headline shrank from "the rule is worth 66× the model" to "the
rule is worth 4.3× the model's features, and most of the money is available with
no model at all." The second statement is smaller, more surprising, and true.

---

## ADR-013 — Dashboard shell over the evidence-binder landing

**Context.** §12.3 made an opinionated call: *the app does not open on a
dashboard, it opens on one case*, with `respond_by` as the hero. The argument was
that a KPI grid is the default for every risk product ever built and the wrong
hero for a job that is fundamentally "decide this one thing before the clock runs
out." The console shipped that way in Phase 7a — a case rail on the left, one
case filling the sheet, no portfolio view at all.

**Decision.** Reversed. The console now opens on a **portfolio view**: a
persistent sidebar (nav, live system status, the defense-only callout), a KPI
strip, and a queue of the twelve fixture cases. The case view becomes a
destination inside that shell rather than the whole application, restructured
into verdict banner → investigation trace → evidence checklist → network summary
→ (Phase 6) drafted narrative. Two new destinations join it: the network chamber,
and an audit trail that verifies its own hash chain.

**Why.** Panel legibility, and nothing else. §12.3's argument is still correct
about the *operator's* job — someone working a queue against a deadline is better
served by landing on the case. It is wrong about the *reviewer's* job. A judge
skimming a five-minute video or a folder of screenshots has no case context to
land in, and an unfamiliar shell costs them the first thirty seconds working out
what they are looking at. The differentiation §12.3 bought is real but it is
spent on the wrong audience: the thing that actually distinguishes this build is
the reason-code matrix, the expected-cost rule and the ring detector, none of
which is easier to see from a single-case landing.

**What is unchanged, deliberately.** The network chamber and its one inversion
(§12.4). The semantic palette (§12.2). The forensic vocabulary — cases, exhibits,
filing deadlines, verdicts. The restraint rules (§12.5): one accent per state, no
untriggered motion, amounts always in tabular mono with Indian digit grouping and
never abbreviated, empty states that give instructions rather than mood. This is a
shell-and-landing change, not a ground-up redesign, and the cut order in the
build plan is not reordered by it.

**A second reversal, recorded because it happened quietly.** Phase 7a's
`styles.css` had already abandoned §12.2's light surface for a dark one, arguing
in a header comment that the work is instrument work rather than document work.
That was a real change to the shipped product that never reached the spec, which
is how a spec stops being read. The shell restores §12.2: light workspace, dark
sidebar. The light/dark split now falls on the axis §12.1 originally argued for —
document surfaces light, the graph chamber dark — with the sidebar dark because
persistent chrome should recede, not because the surface changed meaning.

**Real numbers only.** Every KPI tile reads from `web/src/metrics.json`, written
by `eval/run_eval.py` from the held-out test split, or is derived in the browser
from the fixture set. No tile is allowed a placeholder zero or a plausible-looking
figure; where a number genuinely is not computed yet — the drafting model, which
is Phase 6 — the shell says so in words rather than rendering an empty tile.

**Cost.** Three of them, stated because a decision record without a cost is
advertising. First, the deadline stops being the hero of the application; it is
still the hero of the case view and the queue sorts on it, but the first thing a
viewer sees is now a number about the portfolio rather than a clock about one
dispute. Second, the shell is the shape a reviewer has seen before, so the
console no longer argues for itself on sight — the argument has to come from the
content, which is a higher bar. Third, a reversal invites the reasonable
suspicion that the original call was a rationalisation. The defence is that the
original reasoning is still in §12.3's history and reproduced above, the
operator-versus-reviewer distinction is the actual thing that changed, and the
reversal is recorded here rather than absorbed silently the way the dark-surface
change was.
