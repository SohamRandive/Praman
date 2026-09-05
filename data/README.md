# Corpus: what is real and what is synthetic

Every dispute in `corpus/` is generated. Nothing here is production data and no
real person, merchant or card appears in it. This file exists so a skeptical
reviewer can decide how much to believe, without reading the engine.

Every number below is printed by the two commands that regenerate it. If a
figure cannot be reproduced by them, it does not belong in this file.

```bash
make data          # regenerate, bit-identically, from the seed
make validate      # print the checks below from the corpus itself
make trace         # watch one case go through the engine, stage by stage
```

## What is real, what is assumed

| Component | Status |
|---|---|
| Reason codes, titles, descriptions | **Real** - from the published Submit Evidence documentation |
| Required-evidence document lists | **Real** - same source |
| `contest()` API evidence field names | **Real** - Disputes API reference |
| Dispute entity shape, phases, statuses | **Real** |
| Identifier formats (`disp_`, `pay_`, `order_`, `acc_`) | **Real** shape, generated values |
| Required vs supporting split | **Our judgement** - the documentation publishes a flat list with no required/optional distinction |
| Network attribution (Visa / Mastercard / Amex / RuPay) | **Inferred** from code format |
| Merchant, claimant and ring behaviour | **Assumed** - see `generator/archetypes.py` |
| Issuer win/loss behaviour | **Assumed** - a noise model, not observed |
| Contest cost Rs 350 | **Assumed** - a defensible default, merchant-configurable |

See `reason_codes.yaml` for the per-row verification status and the date each
row was last checked against the live documentation.

Two entries deserve emphasis, because they move every downstream number:

- **The required/supporting split is ours.** The documentation lists suggested
  documents without saying which are mandatory. Splitting that list produces
  `completeness_score` and therefore winnability. One such call is recorded
  inline in `reason_codes.yaml` for RZP06: requiring shipping proof, billing
  proof *and* correspondence together made 88% of those cases unwinnable on
  paperwork alone, which said more about our reading than about the merchants.
- **Issuer behaviour is a noise model.** Real issuers differ substantially by
  bank. Ours is homogeneous, which is a limit rather than a convenience.

## Ground truth is factored, not asserted

```
gt_winnable = (not merchant_at_fault) and evidence_sufficient
```

The two halves are generated independently:

- `merchant_at_fault` comes from the merchant's fulfilment reliability and the
  claimant's grievance prior. **A fact about the world.**
- `evidence_sufficient` comes from resolving the reason code against the matrix
  with the real evidence engine - the same code the product runs. **A fact about
  record-keeping.**

A merchant can be entirely in the right and lose because nobody kept a signed
delivery record. A merchant with immaculate records can lose because they
genuinely failed to deliver. Both exist in volume here, and keeping them
separable is what stops a model learning a shortcut.

The **observed** label is drawn by passing ground truth through a noisy issuer:
14% false-loss on winnable cases,
5% false-win on unwinnable ones, plus
penalties for late filing and phase escalation.

**Train on `observed_won`. Never on a `gt_` column.** Those exist to evaluate the
model and to audit the generator, not to feed either. The guard is an allowlist
in code (`eval/validate_corpus.py`) and a test, not a comment.

## Measured results, seed 20260904

17,500 disputes across 100 merchants, 60 rings
and 90 decoys, 47,544 entity edges. Bit-reproducible
across runs.

| Split | Merchants | Disputes | Share | Winnable | Observed win |
|---|---|---|---|---|---|
| calibration | 15 | 2,625 | 15% | 0.385 | 0.341 |
| test | 25 | 4,375 | 25% | 0.416 | 0.360 |
| train | 60 | 10,500 | 60% | 0.392 | 0.334 |

Splits land on the requested 60/15/25 exactly, with a winnable-rate spread of
0.031 across folds. They are by **merchant**, stratified by archetype *and* by
merchant quality, with split volume balanced at the same time - see ADR-005,
which records what each part fixed.

### The corpus is not rigged, and here is how to check

**No feature outside the label's own definition comes close to solving it.** The
strongest is `evidence_field_count` at **0.603** AUC.

**Evidence cannot observe merchant fault.** `evidence_sufficient` scores
**0.487** AUC against `gt_merchant_at_fault` - indistinguishable from
chance. Nothing in a document cupboard observes whether a merchant actually
failed its customer. That residual is the entire modelling problem, and it can
only be attacked with claimant, merchant and network features.

**Evidence predicts winnability exactly as hard as the definition forces, and no
harder.** `evidence_sufficient` is one of the two conjuncts of `gt_winnable`, so
it must predict the label; asking otherwise would ask the corpus to contradict
itself, and "no feature exceeds 0.64" treats a structurally determined number as
free evidence. Scoring `W = A and B` by the binary `B`, `W = 1` forces `B = 1`,
so TPR is pinned at 1 and the AUC collapses to `(1 + TNR) / 2`. With a
sufficiency rate of 0.708 and a winnable rate of 0.397 the bound computes to
**0.742**; the observed value is **0.742**. That equality is the evidence,
not a low number.

**What the TNR says about the corpus.** Inverting, `TNR = 2 x AUC - 1 =
0.484`: **48% of losses in this corpus are evidence-driven** and the
rest are merchant fault. An earlier corpus sat at TNR 0.266, meaning only 27% of
its losses were something better record-keeping could have prevented. This one is
the better corpus for an evidence product, because more of the loss is the part
the product can actually fix.

**Issuer noise caps achievable performance at AUC 0.897.** A model reporting
above that has a bug or a leak. Check the split and the feature allowlist before
touching hyperparameters.

**Rings and decoys genuinely overlap.** Medians separate them -
23 disputes at 1.26/day against 9 at
0.07/day - but the burst-rate ranges cross
(0.05-5.50 against
0.02-0.94), and **56 of the 90 decoy
groups sit inside the ring burst-rate range**. Decoys are built by the *same code
path* as rings (ADR-006), differing only in temporal concentration and dispute
propensity; building them differently would let a detector learn the artefact
instead of the discrimination. The overlap is where ring precision dies and it is
not designed away.

### Economics: the oracle headroom is a floor

Test split, with every policy deciding and settling on `observed_won` (ADR-010).

| Policy | Net |
|---|---|
| Accept everything | Rs 0 |
| Contest everything | Rs 89,12,555 |
| Oracle, fixed 0.5 threshold | Rs 98,92,905 |
| Oracle + expected-cost rule | Rs 99,10,355 |

The expected-cost rule adds **Rs 17,450**. That is small by construction:
against a *perfect* classifier the rule can only improve disputes worth less than
the cost of contesting them (526 of 4,375 test disputes), because a
perfect classifier already declines everything it would lose. The rule earns its
keep against a calibrated but **imperfect** model, where the threshold `C/A` moves
across the amount range. Phase 3 reports that figure; this one bounds it below.

An earlier version of this table let the oracle rows *decide* on `gt_winnable`
while *settling* on `observed_won`, inflating the headroom by 25%. Any baseline
must decide and settle on the same source of truth - ADR-010.

### Constraints bite

29.2% of disputes carry at least one blocking gap.
3.1% are routed to a human rather than decided.

| Constraint event | Count |
|---|---|
| `blocking:delivery_before_dispute` | 330 |
| `blocking:legibility_check` | 313 |
| `blocking:policy_predates_transaction` | 7 |
| `blocking:refund_amount_matches` | 205 |
| `blocking:refund_amount_matches_payment` | 273 |
| `blocking:shipped_before_cancellation_request` | 96 |
| `rejected:email_channel_only` | 788 |
| `unevaluated:delivered_within_committed_sla` | 301 |
| `unevaluated:shipped_before_cancellation_request` | 320 |
| `warn:delivered_within_committed_sla` | 449 |
| `warn:signature_strongly_preferred` | 1,725 |

Events are labelled by how they fire. `rejected:` is a field qualifier refusing
an artifact at bind time; `blocking:` disqualifies the package; `warn:` shapes
the narrative without blocking; `unevaluated:` is declared unknown. Counting only
violated and unevaluated constraints left `email_channel_only` - enforced at bind
time - out of this table entirely, which is why the labels exist.

The email-not-WhatsApp rule refusing 788 artifacts is the most India-specific
assumption in the design paying off: a large share of Indian SMB support lives on
WhatsApp, and the documentation explicitly excludes it for RZP06 and RZP00. It is
a real, common, silent way merchants lose disputes with paperwork attached.

**Unevaluated constraints are declared, not silently passed** (ADR-008). Where
the generator does not model the fact a constraint needs, it is reported
`unevaluated:<id>` rather than assumed to pass. A constraint governing a document
that is *already* reported missing is marked `not_applicable` instead, so one
absent delivery record counts as one failure rather than two.

## Constraint provenance

Nine constraints govern the matrix. Six instances are published requirements;
eight are our formalisation. Which is which is a first-class field on every
constraint (`source: published | inferred`), enforced at load time - a
constraint that does not declare it is refused, because the required/supporting
split is already our judgement and silence would read as documentation.

| Constraint | Source | Severity | Applies to | Basis |
|---|---|---|---|---|
| `delivery_before_dispute` | *ours* | blocking | 13.1, 1064, C08 | The docs require delivery confirmation but do not state the temporal test. Delivery after the dispute was raised cannot rebut it, so the ordering is ours. |
| `legibility_check` | *ours* | blocking | 1101 | Entirely ours. The docs give 1101, 1102 and 1103 an identical evidence list and say nothing about legibility or OCR. Argued from the code's name: it exists because the previous submission was unreadable. |
| `policy_predates_transaction` | *ours* | blocking | 13.2 | The docs list the cancellation policy as evidence but do not require it to predate the transaction. A policy published afterwards cannot bind the cardholder, so the test is ours. |
| `refund_amount_matches` | *ours* | blocking | 13.6 | The Visa entry lists refund processing proof without a matching requirement. Carried over from the RuPay and Razorpay wording, which does state it. |
| `shipped_before_cancellation_request` | *ours* | blocking | 13.7, C05 | The docs list "Order already processed/shipped" and "Cancellation window missed" as evidence items. Formalising them as a timestamp comparison is ours. |
| `delivered_within_committed_sla` | **published** | warn | RZP06 | RZP06 states "Proof of service/goods delivery in committed timeline". |
| `email_channel_only` | **published** | blocking | RZP06, RZP00 | RZP06 and RZP00 both state "Customer communications over email (not WhatsApp)". |
| `refund_amount_matches_payment` | **published** | blocking | 1061, RZP04 | 1061 and RZP04 both state "Bank statement showing refund amount matching payment". |
| `signature_strongly_preferred` | **published** | warn | 13.1 | Visa "Merchandise/Services Not Received" lists "Delivery confirmation with signature". |

The two that matter most sit on opposite sides of that line. `email_channel_only`
is published verbatim and is the single most load-bearing rule in the matrix,
refusing 788 artifacts across the corpus. `legibility_check` is entirely ours:
the documentation gives 1101, 1102 and 1103 an identical evidence list and says
nothing about legibility. It is argued from the code's name - the code exists
because the previous submission was unreadable, so resubmitting the same scan
loses again - and it is cheap and deterministic. But it is not a requirement,
and it is marked as ours everywhere it appears.

## Files

| File | Contents |
|---|---|
| `disputes.jsonl` | Per dispute: features, evidence detail, ground truth, observed label, split |
| `merchants.jsonl` | Merchant profiles with archetype and split |
| `groups.jsonl` | Rings and decoys with membership, target merchants, `is_abusive` |
| `entity_edges.jsonl` | Cross-merchant entity graph: identity to device / address / instrument |
| `summary.json` | Corpus statistics, config, seed, noise and economics parameters |

Every entity id is a salted hash. No raw email, phone, address or instrument
detail is written to any file, and no PAN exists anywhere in the system.

## Known limits

1. **Absolute numbers are not transferable.** What transfers is the relative
   ordering of policies and the ablations.
2. **The engine defines its own ground truth.** `evidence_sufficient` is computed
   by the same evidence engine the product runs, which removes a duplicated rule
   that would have drifted - but it means the corpus can no longer reveal that
   the engine has *misread the documentation*. A shared misreading propagates
   silently into every number. Verifying `reason_codes.yaml` against the live
   documentation is therefore higher-stakes, not lower, and is checked in CI.
3. **Entity resolution is assumed away.** Members share entities by construction.
   Real Indian address normalisation is hard, false joins create false rings, and
   this corpus does not test that failure mode at all. It is the system's weakest
   real-world link.
4. **No temporal drift.** Merchant hygiene and ring tactics are static across the
   180-day window. Real ones adapt.
5. **Corpus scale is a knob.** `--target-disputes` changes how many disputes are
   drawn and nothing else - no rate and no distribution moves with it.
