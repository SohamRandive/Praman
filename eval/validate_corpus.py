"""Corpus validation: the evidence that the generator is not rigged.

A synthetic corpus is only worth anything if a skeptical reader can check it,
so this prints the checks that would *expose* a rigged one:

  no single feature solves the task   if one did, the corpus would be a lookup
  evidence cannot see merchant fault  the residual is the real modelling problem
  issuer noise caps achievable AUC    a model above the ceiling has a leak
  rings and decoys overlap            they are built by one code path (ADR-006)
  the economics have headroom         independent of any classifier's quality

    python3 -m eval.validate_corpus --corpus data/corpus
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data.generator.archetypes import ECONOMICS
from eval.metrics import auc, median, rupees

# Features a model is allowed to see. Anything prefixed gt_ is evaluation-only.
# This list is the corpus-side mirror of the adjudicator's feature allowlist.
CANDIDATE_FEATURES: dict[str, Any] = {
    "no_blocking_gaps": lambda d: float(d["no_blocking_gaps"]),
    "completeness_score": lambda d: d["completeness_score"],
    "required_coverage": lambda d: d["required_coverage"],
    "evidence_field_count": lambda d: float(d["evidence_field_count"]),
    "evidence_sufficient": lambda d: float(d["evidence_sufficient"]),
    "signature_present": lambda d: float(d["signature_present"]),
    "amount_minor": lambda d: float(d["amount_minor"]),
    "in_group": lambda d: float(d["in_group"]),
    "group_size": lambda d: float(d["group_size"]),
    "group_merchant_span": lambda d: float(d["group_merchant_span"]),
    "payment_captured": lambda d: float(d["payment_captured"]),
    "n_violated_constraints": lambda d: float(len(d["violated_constraints"])),
}


# Features that are functions of the `evidence_sufficient` conjunct of the
# label. They must predict `gt_winnable`; the question is only whether they
# predict it harder than the definition allows.
DEFINITIONAL_FEATURES = frozenset({
    "evidence_sufficient", "no_blocking_gaps", "required_coverage",
    "completeness_score", "n_violated_constraints",
})


def load(corpus: Path) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for name in ("disputes", "merchants", "groups", "entity_edges"):
        path = corpus / f"{name}.jsonl"
        with open(path, encoding="utf-8") as fh:
            out[name] = [json.loads(line) for line in fh]
    return out


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def check_no_leakage(disputes: list[dict[str, Any]]) -> list[str]:
    """Guard, in code rather than in a comment. One leaked ground-truth column
    invalidates every number downstream and it is the easiest mistake to make."""
    problems = []
    gt_columns = {k for k in disputes[0] if k.startswith("gt_")}
    leaked = gt_columns & set(CANDIDATE_FEATURES)
    if leaked:
        problems.append(f"ground-truth columns in the feature set: {sorted(leaked)}")
    if "observed_won" in CANDIDATE_FEATURES:
        problems.append("the training label is in the feature set")
    return problems


def economics(rows: list[dict[str, Any]], cost: int) -> dict[str, int]:
    """Four policies, valued in rupees. The money is already debited, so
    accepting nets zero and contesting costs `cost` whatever the outcome.

    Every row here decides and settles on `observed_won` (ADR-010). Deciding on
    `gt_winnable` while paying out on `observed_won` is not an oracle - it is a
    rule that knows the truth making bets settled against a noisy outcome, and
    it hands free credit to whichever policy declines the cases where the two
    disagree. That inflated an earlier version of this table by 25%.
    """
    contest_all = sum((d["amount_minor"] if d["observed_won"] else 0) - cost for d in rows)
    won = [d for d in rows if d["observed_won"]]
    oracle_fixed = sum(d["amount_minor"] - cost for d in won)
    oracle_ev = sum(d["amount_minor"] - cost for d in won if d["amount_minor"] > cost)
    return {
        "accept_everything": 0,
        "contest_everything": contest_all,
        "oracle_fixed_threshold": oracle_fixed,
        "oracle_expected_cost_rule": oracle_ev,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="data/corpus")
    ap.add_argument("--cost-minor", type=int, default=ECONOMICS.contest_cost_minor)
    args = ap.parse_args(argv)

    corpus = Path(args.corpus).resolve()
    data = load(corpus)
    disputes, groups = data["disputes"], data["groups"]
    with open(corpus / "summary.json", encoding="utf-8") as fh:
        summary = json.load(fh)
    failures: list[str] = []

    print(f"corpus: {corpus}")
    c = summary["counts"]
    print(f"{c['disputes']:,} disputes  {c['merchants']} merchants  "
          f"{c['rings']} rings  {c['decoys']} decoys  {c['entity_edges']:,} entity edges")

    # ---------------------------------------------------------------- leakage
    section("1. Ground-truth leakage guard")
    problems = check_no_leakage(disputes)
    gt_cols = sorted(k for k in disputes[0] if k.startswith("gt_"))
    print(f"  evaluation-only columns: {', '.join(gt_cols)}")
    print(f"  candidate features:      {len(CANDIDATE_FEATURES)}")
    if problems:
        failures.extend(problems)
        for p in problems:
            print(f"  FAIL {p}")
    else:
        print("  PASS no ground-truth column and no label is reachable as a feature")

    # ----------------------------------------------------------------- splits
    section("2. Split balance (split by merchant, stratified by archetype and quality)")
    print(f"  {'split':<12}{'disputes':>10}{'share':>8}{'merchants':>11}"
          f"{'winnable':>10}{'observed':>10}")
    rates = []
    for name, v in summary["splits"].items():
        print(f"  {name:<12}{v['disputes']:>10,}{v['share']:>8.0%}{v['merchants']:>11}"
              f"{v['winnable_rate']:>10.3f}{v['observed_win_rate']:>10.3f}")
        rates.append(v["winnable_rate"])
    spread = max(rates) - min(rates)
    print(f"  winnable-rate spread across folds: {spread:.3f}")
    if spread > 0.08:
        failures.append(f"winnable rate shifts {spread:.3f} across folds")
        print("  FAIL distribution shift across folds")
    else:
        print("  PASS no material distribution shift")

    # --------------------------------------------------- single-feature power
    section("3. No single feature solves the task (AUC vs gt_winnable)")
    labels = [d["gt_winnable"] for d in disputes]
    scored = sorted(
        ((name, auc([fn(d) for d in disputes], labels)) for name, fn in CANDIDATE_FEATURES.items()),
        key=lambda kv: -abs(kv[1] - 0.5),
    )
    for name, value in scored:
        mark = "  (definitional)" if name in DEFINITIONAL_FEATURES else ""
        print(f"  {name:<28}{value:.3f}{mark}")

    # gt_winnable is *defined* as (not merchant_at_fault) and evidence_sufficient,
    # so an evidence feature is one of the two conjuncts and must predict the
    # label. Asking it not to would be asking the corpus to contradict itself.
    # What can be checked is that it predicts no *better* than the definition
    # forces: for a binary conjunct the AUC is pinned at (1 + TNR) / 2 with
    # TNR = P(not sufficient) / P(not winnable). Anything above that is a leak
    # carrying information the conjunction does not account for.
    q = sum(d["evidence_sufficient"] for d in disputes) / len(disputes)
    w = sum(labels) / len(labels)
    predicted = (1 + (1 - q) / (1 - w)) / 2
    observed = dict(scored)["evidence_sufficient"]
    print(f"\n  evidence_sufficient rate {q:.3f}, winnable rate {w:.3f}")
    print(f"  AUC forced by the conjunction: {predicted:.3f}   observed: {observed:.3f}")
    if abs(observed - predicted) > 0.02:
        failures.append(
            f"evidence_sufficient AUC {observed:.3f} exceeds the {predicted:.3f} "
            f"the definition forces - it is carrying extra information"
        )
        print("  FAIL evidence carries more signal than the definition accounts for")
    else:
        print("  PASS exactly what the definition forces, and nothing more")

    free = [(n, v) for n, v in scored if n not in DEFINITIONAL_FEATURES]
    strongest = max(free, key=lambda kv: abs(kv[1] - 0.5))
    print(f"  strongest non-definitional feature: {strongest[0]} at {strongest[1]:.3f}")
    if abs(strongest[1] - 0.5) > 0.15:
        failures.append(f"{strongest[0]} alone reaches AUC {strongest[1]:.3f}")
        print("  FAIL a feature outside the label definition is close to solving the task")
    else:
        print("  PASS no feature outside the label definition comes close")

    # ------------------------------------------------ evidence vs fault
    section("4. Evidence cannot observe merchant fault (AUC vs gt_merchant_at_fault)")
    fault = [d["gt_merchant_at_fault"] for d in disputes]
    for name in ("no_blocking_gaps", "completeness_score", "evidence_sufficient"):
        value = auc([CANDIDATE_FEATURES[name](d) for d in disputes], fault)
        print(f"  {name:<28}{value:.3f}")
    key = auc([CANDIDATE_FEATURES["no_blocking_gaps"](d) for d in disputes], fault)
    if abs(key - 0.5) > 0.08:
        failures.append(f"evidence sees merchant fault at AUC {key:.3f}")
        print("  FAIL record-keeping is leaking the state of the world")
    else:
        print("  PASS indistinguishable from chance - the residual is the real problem")

    # ------------------------------------------------------------- the ceiling
    section("5. Issuer noise caps achievable performance")
    ceiling = auc([float(d["gt_winnable"]) for d in disputes],
                  [d["observed_won"] for d in disputes])
    print(f"  AUC of gt_winnable against observed_won: {ceiling:.3f}")
    print(f"  A model reporting above {ceiling:.3f} on this corpus has a bug or a leak.")

    # ---------------------------------------------------------- rings, decoys
    section("6. Ring and decoy discrimination (built by one code path - ADR-006)")
    per_group: dict[str, list[dict[str, Any]]] = {}
    for d in disputes:
        if d["group_id"]:
            per_group.setdefault(d["group_id"], []).append(d)
    stats: dict[bool, dict[str, list[float]]] = {
        True: {"n": [], "per_day": [], "span": []},
        False: {"n": [], "per_day": [], "span": []},
    }
    for g in groups:
        rows = per_group.get(g["group_id"], [])
        if not rows:
            continue
        bucket = stats[g["is_abusive"]]
        bucket["n"].append(len(rows))
        bucket["per_day"].append(len(rows) / max(1, g["burst_days"]))
        bucket["span"].append(len({r["merchant_id"] for r in rows}))
    print(f"  {'':<22}{'rings':>10}{'decoys':>10}")
    for label, key_ in (("median disputes", "n"), ("median disputes/day", "per_day"),
                        ("median merchant span", "span")):
        print(f"  {label:<22}{median(stats[True][key_]):>10.2f}{median(stats[False][key_]):>10.2f}")
    r, d_ = stats[True]["per_day"], stats[False]["per_day"]
    overlap = sum(1 for x in d_ if x >= min(r)) if r else 0
    print(f"  burst-rate ranges: rings {min(r):.2f}-{max(r):.2f}  "
          f"decoys {min(d_):.2f}-{max(d_):.2f}")
    print(f"  decoys inside the ring burst-rate range: {overlap} of {len(d_)}")
    print("  That overlap is where ring precision dies. It is not designed away.")

    # ------------------------------------------------------------- economics
    section("7. Economics headroom on the test split (perfect classifier)")
    test = [d for d in disputes if d["split"] == "test"]
    econ = economics(test, args.cost_minor)
    for name, value in econ.items():
        print(f"  {name:<30}{rupees(value):>16}")
    headroom = econ["oracle_expected_cost_rule"] - econ["oracle_fixed_threshold"]
    below = sum(1 for d in test if d["amount_minor"] <= args.cost_minor)
    print(f"\n  The expected-cost rule adds {rupees(headroom)} over a fixed threshold")
    print(f"  at a contest cost of {rupees(args.cost_minor)}.")
    print(f"  {below:,} of {len(test):,} test disputes are worth less than the cost of")
    print("  contesting them, and against a *perfect* classifier those are the only")
    print("  cases the rule can improve - a perfect classifier already skips every")
    print("  case it would lose. So this figure is a floor, not the headline: the")
    print("  rule earns its keep against a calibrated but imperfect model, where the")
    print("  threshold C/A moves with the amount and changes far more decisions.")
    print("  Phase 3 reports that number; this one bounds it from below.")
    if headroom <= 0:
        failures.append("the expected-cost rule adds nothing over a fixed threshold")
        print("  FAIL no headroom")

    # ---------------------------------------------------------------- verdict
    section("verdict")
    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("  all corpus checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
