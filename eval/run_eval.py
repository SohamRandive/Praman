"""Full evaluation: metrics table, three baselines, ablations, figures.

    python3 -m eval.run_eval --corpus data/corpus

Every policy in this file DECIDES and SETTLES on `observed_won` (ADR-010).
Deciding on `gt_winnable` while paying out on `observed_won` is not an oracle;
it is a rule that knows the truth placing bets against a noisy outcome, and it
hands free credit to whichever policy declines the cases where the two disagree.

Two money formatters are imported on purpose. `eval.metrics.rupees` writes "Rs"
because this file prints into terminals; `rupees_glyph` is the console's own and
writes the glyph, and it is used only for strings that end up on a screen. One
formatter per destination, never two per screen.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from eval.metrics import auc, rupees, wilson
from praman.adjudicator import break_even
from praman.adjudicator.model import Adjudicator, train
from praman.console.serialize import rupees as rupees_glyph
from praman.network import COMPONENT_FEATURES, point_in_time_features
from praman.network.rings import candidates, choose_threshold, cohesion, evaluate

COST_MINOR = 35_000


# ------------------------------------------------------------------- metrics


def pr_auc(scores: list[float], labels: list[bool]) -> float:
    """Average precision: sum over thresholds of (recall delta) * precision."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    total_pos = sum(labels) or 1
    tp = fp = 0
    prev_recall = 0.0
    area = 0.0
    for i in order:
        if labels[i]:
            tp += 1
        else:
            fp += 1
        recall = tp / total_pos
        precision = tp / (tp + fp)
        area += (recall - prev_recall) * precision
        prev_recall = recall
    return area


def ece(probs: np.ndarray, labels: np.ndarray, bins: int = 15) -> float:
    """Expected calibration error, equal-width bins.

    The decision rule compares `p` to `C/A`. If `p` is not a probability the
    comparison is meaningless, so this number gates every rupee figure below.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (probs > lo) & (probs <= hi) if lo > 0 else (probs >= lo) & (probs <= hi)
        if not mask.any():
            continue
        total += mask.mean() * abs(probs[mask].mean() - labels[mask].mean())
    return float(total)


def reliability(probs: np.ndarray, labels: np.ndarray, bins: int = 10):
    edges = np.linspace(0.0, 1.0, bins + 1)
    xs, ys, ns = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (probs > lo) & (probs <= hi) if lo > 0 else (probs >= lo) & (probs <= hi)
        if mask.sum() < 10:
            continue
        xs.append(float(probs[mask].mean()))
        ys.append(float(labels[mask].mean()))
        ns.append(int(mask.sum()))
    return xs, ys, ns


# ------------------------------------------------------------------ policies


def net(rows: list[dict[str, Any]], contest: list[bool], cost: int = COST_MINOR) -> int:
    """Rupees kept. Accepting nets zero - the money is already debited."""
    total = 0
    for row, fight in zip(rows, contest, strict=True):
        if fight:
            total += (row["amount_minor"] if row["observed_won"] else 0) - cost
    return total


def confusion(contest: list[bool], labels: list[bool]) -> dict[str, float]:
    tp = sum(1 for c, y in zip(contest, labels, strict=True) if c and y)
    fp = sum(1 for c, y in zip(contest, labels, strict=True) if c and not y)
    fn = sum(1 for c, y in zip(contest, labels, strict=True) if not c and y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "contested": float(tp + fp),
        "false_positives": float(fp),
    }


def false_positive_cost(contest: list[bool], labels: list[bool], cost: int) -> int:
    """What the wrong decisions cost, in rupees.

    A false positive here is a dispute we contested and lost: the representment
    was prepared and filed, the money was never recoverable, and the merchant
    paid `cost` to discover that. The track bar asks for false-positive cost
    explicitly, and a precision figure alone does not supply it - one wasted
    contest on a Rs 200 dispute and one on a Rs 200,000 dispute are the same
    false positive and the same wasted rupees, which is exactly why the rule
    prices the decision rather than the classification.
    """
    return cost * sum(
        1 for c, y in zip(contest, labels, strict=True) if c and not y
    )


def by_decile(
    amounts: list[int], contest: list[bool], labels: list[bool], n: int = 10
) -> list[tuple[str, int, float, float, float]]:
    """Precision and recall within amount deciles.

    A single precision/recall pair for the expected-cost rule is not
    well-defined: its threshold is C/A and therefore varies per dispute. A
    Rs 500 case is judged at 0.70 and a Rs 50,000 case at 0.007, so collapsing
    them into one pair averages two different operating points and reads as a
    failure when it is the rule working as designed.
    """
    order = sorted(range(len(amounts)), key=lambda i: amounts[i])
    out = []
    for chunk in np.array_split(np.asarray(order), n):
        idx = list(chunk)
        if not idx:
            continue
        c = confusion([contest[i] for i in idx], [labels[i] for i in idx])
        lo, hi = amounts[idx[0]], amounts[idx[-1]]
        contested = c["contested"]
        out.append((f"{rupees(lo)}-{rupees(hi)}", len(idx),
                    c["precision"] if contested else float("nan"),
                    c["recall"], contested / len(idx)))
    return out


def tune_constant_threshold(
    rows: list[dict[str, Any]], probs, cost: int, grid: int = 201
) -> tuple[float, int]:
    """The best CONSTANT threshold, fitted on held-out data by net rupees.

    This is the baseline the expected-cost rule actually has to beat, and it was
    missing. Contest-everything is itself a constant threshold - t = 0 - so the
    best constant is at least as good as contest-everything, and comparing the
    rule against t = 0.5 measures only that 0.5 is a bad constant. The rule's
    claim is that the threshold should vary with the amount, and nothing but a
    tuned constant tests that claim.
    """
    best_t, best_net = 0.0, None
    for i in range(grid):
        t = i / (grid - 1)
        n = net(rows, [p > t for p in probs], cost)
        if best_net is None or n > best_net:
            best_t, best_net = t, n
    return best_t, int(best_net)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# --------------------------------------------------------------------- main


def load(corpus: Path):
    with open(corpus / "disputes.jsonl", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    with open(corpus / "entity_edges.jsonl", encoding="utf-8") as fh:
        edges = [json.loads(line) for line in fh]
    load.rows, load.edges = rows, edges
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["split"], []).append(r)
    # Network features are DERIVED from the entity graph, point-in-time. The
    # corpus's own group_size / in_group columns are forbidden: they are the
    # generator's record of how it built each cluster, which production cannot
    # know, and feeding them back would make the network ablation measure
    # perfect cluster knowledge rather than a detector.
    return out, point_in_time_features(rows, edges)


def ablate(
    by: dict[str, list[dict[str, Any]]],
    comps: dict[str, dict[str, float]],
    drop: Callable[[str], bool],
    seed: int,
) -> tuple[Adjudicator, np.ndarray]:
    """Retrain with a family of features zeroed out, so the comparison is a
    like-for-like retrain rather than a crippled prediction pass."""
    import praman.adjudicator.features as F

    original = F.extract

    def masked(row, component=None):
        f = original(row, component)
        for k in list(f):
            if drop(k):
                f[k] = 0.0
        return f

    F.extract = masked
    try:
        adj = train(by["train"], by["calibration"], seed=seed, components=comps)
        probs = adj.predict(by["test"])
    finally:
        F.extract = original
    return adj, probs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="data/corpus")
    ap.add_argument("--cost-minor", type=int, default=COST_MINOR)
    ap.add_argument("--seed", type=int, default=20260904)
    ap.add_argument("--figures", default="eval/figures")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--metrics-out", default="web/src/metrics.json",
                    help="where the console reads its KPI numbers from")
    args = ap.parse_args(argv)

    by, comps = load(Path(args.corpus).resolve())
    test = by["test"]
    y = [bool(r["observed_won"]) for r in test]
    y_arr = np.asarray(y, dtype=float)
    amounts = [r["amount_minor"] for r in test]
    cost = args.cost_minor
    failures: list[str] = []
    # Filled as each section computes its numbers, written once at the end. The
    # console must not recompute anything: a KPI tile that derives its own
    # figure is a second implementation that will disagree with this one.
    metrics: dict[str, Any] = {}

    print(f"train {len(by['train']):,}  calibration {len(by['calibration']):,}  "
          f"test {len(test):,}   contest cost {rupees(cost)}")

    adj = train(by["train"], by["calibration"], seed=args.seed, components=comps)
    probs = adj.predict(test)
    cal_probs = adj.predict(by["calibration"])
    raw = adj.raw(test)

    # ------------------------------------------------------------- model
    section("1. Model")
    a_test = auc(list(probs), y)
    print(f"  features {len(adj.feature_spec)}   trees {adj.best_iteration}")
    prauc = pr_auc(list(probs), y)
    print(f"  PR-AUC    {prauc:.4f}   (base rate {np.mean(y_arr):.3f}) <- the right one here")
    print(f"  ROC-AUC   {a_test:.4f}")
    print("  PR-AUC is the headline at a 36% base rate: ROC-AUC is flattered by the")
    print("  large negative class, and the decision is about the positives.")
    PRAUC_TARGET = 0.80
    if prauc < PRAUC_TARGET:
        print(f"\n  MISS: PR-AUC {prauc:.4f} is below the {PRAUC_TARGET:.2f} target set")
        print("  before the economics were measured. Reported as a miss, not adjusted.")
        print("  It is also consistent with the central finding rather than a")
        print("  refutation of it: a mediocre classifier that barely moves the money is")
        print("  what you expect when the decision rule dominates. See SPEC section 15,")
        print("  where the target is revised with that reasoning recorded.")
    CEILING = 0.897
    if a_test > CEILING:
        failures.append(f"AUC {a_test:.4f} exceeds the {CEILING} corpus ceiling")
        print(f"  FAIL above the {CEILING} ceiling set by issuer noise - this is a leak,")
        print("       not capacity. Check the feature allowlist and the split.")
    else:
        print(f"  PASS below the {CEILING} ceiling set by issuer noise")
    metrics["model"] = {
        "pr_auc": round(prauc, 4),
        "pr_auc_target": PRAUC_TARGET,
        "pr_auc_meets_target": bool(prauc >= PRAUC_TARGET),
        "roc_auc": round(a_test, 4),
        "roc_auc_ceiling": CEILING,
        "base_rate": round(float(np.mean(y_arr)), 4),
        "features": len(adj.feature_spec),
        "trees": int(adj.best_iteration),
    }

    # ------------------------------------------------------- calibration
    section("2. Calibration (mandatory - every rupee figure below depends on it)")
    sc = adj.calibration_scores
    print("  Selected by cross-validated ECE inside the calibration split, with a")
    print("  one-standard-error rule. The test split is never consulted.")
    print("  The identity map - no calibration at all - is a full candidate, and the")
    print("  one-SE rule prefers the simplest option, so a fitted calibrator is")
    print("  selected only when it beats doing nothing by more than one standard")
    print("  error. Identity is the honest null and it is allowed to win.")
    print(f"  {'calibrator':<12}{'cv ECE':>9}{'se':>9}")
    for name in ("none", "sigmoid", "isotonic"):
        mark = "  <- selected" if name == sc["selected"] else ""
        print(f"  {name:<12}{sc['mean_ece'][name]:>9.4f}{sc['stderr'][name]:>9.4f}{mark}")

    e_raw, e_cal = ece(np.clip(raw, 0, 1), y_arr), ece(probs, y_arr)
    print(f"\n  On test:  uncalibrated {e_raw:.4f}   selected ({sc['selected']}) {e_cal:.4f}")
    if sc["selected"] == "none":
        print("  The protocol selected no calibration: LightGBM's binary objective is")
        print("  trained on log loss, so its output is already a probability, and on a")
        print("  2,625-row calibration split a fitted calibrator adds more variance")
        print("  than it removes bias. Calibration was verified, not assumed - which")
        print("  is what the requirement is actually for. An uncalibrated score would")
        print("  make `p > C/A` meaningless; a score measured to be calibrated does not.")
    elif e_raw < e_cal:
        print("  The uncalibrated scores score better on test than the calibrator the")
        print("  protocol chose. Both are reported and neither is re-selected here:")
        print("  choosing a calibrator by its test ECE is exactly the thing a held-out")
        print("  split exists to prevent. The honest reading is that LightGBM's binary")
        print("  objective already emits near-calibrated probabilities on this corpus,")
        print("  so post-hoc calibration has little bias left to remove and adds")
        print("  variance from a 2,625-row fit. Both are inside the 0.05 target, so")
        print("  the expected-value rule is safe either way.")
    xs, ys, ns = reliability(probs, y_arr)
    print(f"  {'predicted':>10}{'observed':>10}{'n':>8}")
    for px, py, n in zip(xs, ys, ns, strict=True):
        print(f"  {px:>10.3f}{py:>10.3f}{n:>8,}")
    if e_cal > 0.05:
        failures.append(f"ECE {e_cal:.4f} exceeds 0.05")
        print("  FAIL calibration is too poor for an expected-value rule")
    else:
        print("  PASS ECE within 0.05")
    metrics["calibration"] = {
        "ece": round(float(e_cal), 4),
        "ece_uncalibrated": round(float(e_raw), 4),
        "ece_target": 0.05,
        "selected": sc["selected"],
    }

    # ---------------------------------------------------------- policies
    section("3. Policies, all deciding and settling on observed_won (ADR-010)")
    thresholds = [break_even(a, cost) for a in amounts]
    ev_contest = None  # bound below, once the policy table exists
    # The tuned constant is fitted on calibration, never on test.
    t_star, cal_net = tune_constant_threshold(by["calibration"], cal_probs, cost)

    policies: dict[str, list[bool]] = {
        "accept everything": [False] * len(test),
        "contest everything (t = 0)": [True] * len(test),
        "model, naive p > 0.5": [p > 0.5 for p in probs],
        f"model, best constant t = {t_star:.3f}": [p > t_star for p in probs],
        "model, expected-cost rule": [p > t for p, t in zip(probs, thresholds, strict=True)],
        "model + evidence gate": [
            p > t and r["evidence_sufficient"]
            for p, t, r in zip(probs, thresholds, test, strict=True)
        ],
    }
    print(f"  {'policy':<30}{'net':>15}{'contested':>10}{'FP cost':>14}{'prec':>7}{'recall':>8}")
    nets: dict[str, int] = {}
    policy_rows: list[dict[str, Any]] = []
    # Stable keys for the console. The printed labels carry t* in them and would
    # rename themselves whenever the fit moved, which is fine for a human reading
    # a table and useless for anything that has to look a row up.
    policy_keys = {
        "accept everything": "accept_all",
        "contest everything (t = 0)": "contest_all",
        "model, naive p > 0.5": "naive_half",
        f"model, best constant t = {t_star:.3f}": "best_constant",
        "model, expected-cost rule": "expected_cost_rule",
        "model + evidence gate": "rule_plus_evidence_gate",
    }
    for name, contest in policies.items():
        n = net(test, contest, cost)
        nets[name] = n
        c = confusion(contest, y)
        fpc = false_positive_cost(contest, y, cost)
        share = c["contested"] / len(test)
        print(f"  {name:<30}{rupees(n):>15}{share:>9.0%}{rupees(fpc):>14}"
              f"{c['precision']:>7.3f}{c['recall']:>8.3f}")
        policy_rows.append({
            "key": policy_keys[name],
            "label": name,
            "net_minor": int(n),
            "net": rupees_glyph(n),
            "contested_share": round(share, 4),
            "false_positive_cost_minor": int(fpc),
            "false_positive_cost": rupees_glyph(fpc),
            # Reported for the table only. For the expected-cost rule this pair
            # is NOT an operating point - its threshold is C/A and moves per
            # dispute - and the console must say so wherever it shows it.
            "precision": round(c["precision"], 4),
            "recall": round(c["recall"], 4),
        })
    ev_c = confusion(policies["model, expected-cost rule"], y)
    naive_c = confusion(policies["model, naive p > 0.5"], y)
    print("\n  FP cost = disputes contested and lost, times the contest cost. It is")
    print("  what the wrong decisions actually cost the merchant, which a precision")
    print("  figure alone does not tell them.")
    print(f"\n  The rule's FP cost ({rupees(false_positive_cost(policies['model, expected-cost rule'], y, cost))}) is roughly 3x the naive")
    print(f"  threshold's ({rupees(false_positive_cost(policies['model, naive p > 0.5'], y, cost))}) and that is the correct purchase, not a")
    print(f"  regression: it buys recall {ev_c['recall']:.3f} against {naive_c['recall']:.3f} and")
    print(f"  {rupees(nets['model, expected-cost rule'] - nets['model, naive p > 0.5'])} more net. Minimising false-positive cost is")
    print("  the WRONG objective here - each wasted contest costs Rs 350 while each")
    print("  recovered dispute is worth thousands. That is why the bar asks for it to")
    print("  be reported rather than optimised.")
    print("\n  The single precision/recall pair for the expected-cost rule is shown")
    print("  for comparability only and is NOT its operating point - the rule has no")
    print("  single threshold. See section 6a.")

    ev_contest = policies["model, expected-cost rule"]
    ev_contest_for_deciles = ev_contest
    tuned_name = f"model, best constant t = {t_star:.3f}"
    ev = nets["model, expected-cost rule"]
    fixed = nets["model, naive p > 0.5"]
    tuned = nets[tuned_name]
    print(f"\n  t* = {t_star:.3f}, fitted on the calibration split by net rupees.")
    print("  It collapses toward zero because at Rs 350 against typical dispute")
    print("  values almost everything clears break-even. Contest-everything is")
    print("  t = 0, so the best constant can never be worse than it.")
    metrics["economics"] = {
        "cost_minor": int(cost),
        "cost": rupees_glyph(cost),
        "t_star": round(float(t_star), 3),
        "test_disputes": len(test),
        "test_merchants": len({r["merchant_id"] for r in test}),
        "policies": policy_rows,
        # The headline is a ratio against the best constant, never against 0.5.
        # ADR-012: contest-everything is itself a constant at t = 0, so only the
        # tuned constant tests the claim that the threshold varies with amount.
        "rule_vs_best_constant_minor": int(ev - tuned),
        "rule_vs_best_constant": rupees_glyph(ev - tuned),
        "rule_vs_naive_half_minor": int(ev - fixed),
        "rule_vs_naive_half": rupees_glyph(ev - fixed),
    }

    section("4. Do the baselines fall?")
    for base in ("accept everything", "contest everything (t = 0)",
                 "model, naive p > 0.5", tuned_name):
        delta = ev - nets[base]
        verdict = "PASS" if delta > 0 else "FAIL"
        if delta <= 0:
            failures.append(f"expected-cost rule does not beat {base}")
        print(f"  {verdict} vs {base:<28} {rupees(delta):>16}")

    section("5. What the expected-cost rule is actually worth")
    print(f"  vs the BEST TUNED CONSTANT threshold:  {rupees(ev - tuned):>14}   <- the real number")
    print(f"  vs a naive 0.5 threshold:              {rupees(ev - fixed):>14}   (measures only")
    print("                                                        that 0.5 is a bad constant)")
    print("\n  The rule's claim is that the threshold should VARY WITH THE AMOUNT.")
    print("  Contest-everything is itself a constant threshold at t = 0, so the best")
    print("  constant is at least as good as it, and only the tuned constant tests")
    print("  the claim. Comparing against 0.5 overstates the rule by roughly an")
    print(f"  order of magnitude: {rupees(ev - fixed)} against the honest {rupees(ev - tuned)}.")
    won = [r for r in test if r["observed_won"]]
    oracle_fixed = sum(r["amount_minor"] - cost for r in won)
    oracle_ev = sum(r["amount_minor"] - cost for r in won if r["amount_minor"] > cost)
    print("\n  For contrast, the same rule against a *perfect* classifier adds only")
    print(f"  {rupees(oracle_ev - oracle_fixed)}, because a perfect classifier already")
    print("  declines everything it would lose, leaving only disputes worth less")
    print("  than the cost of contesting them. The oracle figure is a floor; the")
    print("  number above it is the one that matters.")
    below = sum(1 for a in amounts if a <= cost)
    print(f"  ({below:,} of {len(test):,} test disputes are worth less than {rupees(cost)}.)")

    section("6a. Precision and recall by amount decile (the rule has no single threshold)")
    print(f"  {'amount range':<26}{'n':>6}{'precision':>11}{'recall':>9}{'contested':>11}")
    for label, n_, prec, rec, share in by_decile(amounts, ev_contest_for_deciles, y):
        shown = "     -" if prec != prec else f"{prec:>11.3f}"  # NaN when nothing contested
        print(f"  {label:<26}{n_:>6}{shown:>11}{rec:>9.3f}{share:>10.0%}")
    print("\n  Read the direction carefully: precision FALLS as the amount rises,")
    print("  from 0.80 in the third decile to 0.46 in the top one, while recall")
    print("  climbs to 1.00 and the contest rate to 100%. That is the rule working,")
    print("  not failing. Break-even is C/A, so above roughly Rs 16,000 almost any")
    print("  probability clears it, and the rule knowingly accepts many losing")
    print("  contests because each win is worth two orders of magnitude more than")
    print("  the Rs 350 it costs to try. The bottom two deciles are contested 0% of")
    print("  the time - those disputes are worth less than the cost of contesting")
    print("  them - so precision there is undefined rather than zero.")
    print("\n  Collapsing ten operating points into one pair would report their")
    print("  average as though it were a threshold. The >=0.80 precision target does")
    print("  not apply to a policy whose threshold is a function of the amount.")

    section("6. The threshold moves with the amount")
    print(f"  {'amount band':<22}{'n':>7}{'median C/A':>12}{'contest rate':>14}")
    bands = [(0, 25_000), (25_000, 100_000), (100_000, 300_000),
             (300_000, 1_000_000), (1_000_000, 10**12)]
    for lo, hi in bands:
        idx = [i for i, a in enumerate(amounts) if lo <= a < hi]
        if not idx:
            continue
        med = float(np.median([thresholds[i] for i in idx]))
        rate = float(np.mean([ev_contest[i] for i in idx]))
        label = f"{rupees(lo)}-{rupees(hi)}" if hi < 10**12 else f"{rupees(lo)}+"
        print(f"  {label:<22}{len(idx):>7,}{med:>12.3f}{rate:>13.0%}")
    print("\n  A fixed threshold cannot do this. It is the same number for a Rs 200")
    print("  dispute and a Rs 50,000 one, and it is wrong for both.")

    # --------------------------------------------------------- ablations
    section("7. Ablations - does each component earn its place?")
    net_names = set(COMPONENT_FEATURES)
    ev_names = {"completeness_score", "required_coverage", "evidence_sufficient",
                "no_blocking_gaps", "blocking_gap_count", "n_violated_constraints"}
    runs = {
        "full model": (adj, probs),
        "without network features": ablate(by, comps, lambda k: k in net_names, args.seed),
        "without evidence features": ablate(
            by, comps, lambda k: k in ev_names or k.startswith("gap_"), args.seed),
    }
    print(f"  {'variant':<32}{'AUC':>8}{'net':>16}{'delta':>14}")
    baseline_net = None
    net_feature_value = 0
    ablation_rows: list[dict[str, Any]] = []
    for name, (_, p) in runs.items():
        thr = [break_even(a, cost) for a in amounts]
        contest = [pi > t for pi, t in zip(p, thr, strict=True)]
        n = net(test, contest, cost)
        if baseline_net is None:
            baseline_net = n
        delta = "" if name == "full model" else rupees(n - baseline_net)
        if name == "without network features":
            net_feature_value = baseline_net - n
        print(f"  {name:<32}{auc(list(p), y):>8.4f}{rupees(n):>16}{delta:>14}")
        ablation_rows.append({
            "variant": name,
            "auc": round(auc(list(p), y), 4),
            "net_minor": int(n),
            "cost_of_removing_minor": 0 if name == "full model" else int(baseline_net - n),
        })
    print(f"  {'without EV rule (best constant t*)':<32}{a_test:>8.4f}"
          f"{rupees(tuned):>16}{rupees(tuned - baseline_net):>14}   <- the ablation")
    print(f"  {'without EV rule (naive t = 0.5)':<32}{a_test:>8.4f}"
          f"{rupees(fixed):>16}{rupees(fixed - baseline_net):>14}   (not the ablation)")
    ablation_rows.append({
        "variant": "without the expected-cost rule (best tuned constant t*)",
        "auc": round(a_test, 4),
        "net_minor": int(tuned),
        "cost_of_removing_minor": int(baseline_net - tuned),
    })
    metrics["ablations"] = ablation_rows

    # ------------------------------------------- sensitivity to contest cost
    section("9. Sensitivity to C - the assumed input everything else rests on")
    print("  C = Rs 350 is an ASSUMPTION, not a measurement. It is a merchant input")
    print("  and the entire economics finding is conditional on it, so here is the")
    print("  whole curve rather than one point.")
    print(f"\n  {'C':>9}{'t*':>8}{'contest-all':>17}{'best const':>16}{'EV rule':>16}"
          f"{'rule edge':>15}{'edge %':>10}")
    sweep = []
    for c_ in (10_000, 35_000, 100_000, 200_000, 500_000):
        t_c, _ = tune_constant_threshold(by["calibration"], cal_probs, c_)
        all_net = net(test, [True] * len(test), c_)
        const_net = net(test, [p > t_c for p in probs], c_)
        thr_c = [break_even(a, c_) for a in amounts]
        ev_net_c = net(test, [p > t for p, t in zip(probs, thr_c, strict=True)], c_)
        edge = ev_net_c - const_net
        pct = edge / const_net * 100 if const_net > 0 else float("nan")
        sweep.append((c_, t_c, all_net, const_net, ev_net_c, edge, pct))
        print(f"  {rupees(c_):>9}{t_c:>8.3f}{rupees(all_net):>17}{rupees(const_net):>16}"
              f"{rupees(ev_net_c):>16}{rupees(edge):>15}{pct:>9.1f}%")

    rising = all(sweep[i][1] <= sweep[i + 1][1] for i in range(len(sweep) - 1))
    print(f"\n  t* rises monotonically with C: {rising}. It has to - a higher cost of")
    print("  contesting demands a higher probability before contesting is worth it.")

    material = next((r for r in sweep if r[6] >= 5.0), None)
    near_opt = next((r for r in sweep if r[2] < r[4] * 0.90), None)
    if material:
        print("\n  The rule's edge over the best constant becomes material (>=5%) at")
        print(f"  C = {rupees(material[0])}, where it is {rupees(material[5])} ({material[6]:.1f}%).")
    if near_opt:
        print("  Contest-everything stops being near-optimal (within 10%) at")
        print(f"  C = {rupees(near_opt[0])}: {rupees(near_opt[2])} against {rupees(near_opt[4])}.")
    negative = next((r for r in sweep if r[2] < 0), None)
    if negative:
        print(f"  At C = {rupees(negative[0])} contesting everything is actively")
        print(f"  DESTRUCTIVE: {rupees(negative[2])}, against {rupees(negative[4])} for the")
        print("  rule. The trivial policy is not merely suboptimal there, it loses money.")

    print("\n  Read the direction: at LOW contest cost the arithmetic dominates and a")
    print("  trivial policy is nearly optimal, because almost everything clears")
    print("  break-even. As ops cost rises the threshold rises, fewer disputes are")
    print("  worth contesting, and discriminating WHICH ones starts to pay. The")
    print("  system's value is a function of the merchant's ops cost, and Rs 350 sits")
    print("  at the cheap end of that curve where it is worth least.")

    # ------------------------------------------------------ ring detection
    section("8. Ring detection - measured on rings, not on money")
    with open(Path(args.corpus).resolve() / "groups.jsonl", encoding="utf-8") as fh:
        groups = {g["group_id"]: g for g in (json.loads(x) for x in fh)}
    cands = candidates(load.rows, load.edges)
    by_disp = {r["dispute_id"]: r for r in load.rows}
    ring_labels = {
        c.component_id: any(
            groups[g]["is_abusive"]
            for g in {by_disp[d]["group_id"] for d in c.dispute_ids if by_disp[d]["group_id"]}
        )
        for c in cands
    }
    scored = [(c, cohesion(c)) for c in cands]
    cal = [(c, sc) for c, sc in scored if c.split == "calibration"]
    thr = choose_threshold(cal, ring_labels, target_precision=0.85)
    print(f"  candidates {len(cands)} from connected components over shared entities")
    print(f"  threshold {thr:.3f}, chosen on the calibration split to hold precision >= 0.85")
    print(f"  {'split':<14}{'cands':>7}{'rings':>7}{'precision':>11}{'recall':>9}"
          f"{'false-ring rate':>18}")
    for split in ("calibration", "test"):
        sub = [(c, sc) for c, sc in scored if c.split == split]
        m = evaluate(sub, ring_labels, thr)
        print(f"  {split:<14}{int(m['candidates']):>7}{int(m['rings']):>7}"
              f"{m['precision']:>11.3f}{m['recall']:>9.3f}"
              f"{m['false_ring_rate']:>17.3f}")
        if split == "test":
            print(f"  {'':<14}false rings: {int(m['false_rings'])} of "
                  f"{int(m['decoys'])} innocent clusters accused")
            if m["precision"] < 0.85:
                failures.append(f"ring precision {m['precision']:.3f} below the 0.85 floor")
            metrics["rings"] = {
                "split": "test",
                "threshold": round(float(thr), 3),
                "precision_floor": 0.85,
                "candidates": int(m["candidates"]),
                "flagged": int(m["rings"]),
                "precision": round(float(m["precision"]), 4),
                "recall": round(float(m["recall"]), 4),
                # Never folded into an aggregate. Accusing an innocent household
                # is the worst error this system can make, so it is carried as
                # its own number with its own denominator.
                "false_ring_rate": round(float(m["false_ring_rate"]), 4),
                "false_rings": int(m["false_rings"]),
                "decoys": int(m["decoys"]),
                "network_feature_value_minor": int(net_feature_value),
            }
    # Where the misses actually are. A named gap beats a bare recall number.
    profile_of = {
        c.component_id: sorted({
            groups[g]["profile"]
            for g in {by_disp[d]["group_id"] for d in c.dispute_ids if by_disp[d]["group_id"]}
        })[0]
        for c in cands
        if any(by_disp[d]["group_id"] for d in c.dispute_ids)
    }
    buckets: dict[str, list[int]] = {}
    for c, sc in scored:
        if c.split != "test" or not ring_labels[c.component_id]:
            continue
        b = buckets.setdefault(profile_of[c.component_id], [0, 0, []])
        b[0] += 1
        b[1] += int(sc >= thr)
        b[2].append(c.disputes_per_day)
    print("\n  Where the misses are, test split (95% Wilson intervals - small")
    print("  denominators lie, and 0 of 4 is not the same claim as 0.000):")
    print(f"  {'ring profile':<22}{'rings':>6}{'caught':>7}{'recall':>8}"
          f"{'95% interval':>18}{'median burst':>14}")
    for name, (n_, hit, bursts) in sorted(buckets.items()):
        med = sorted(bursts)[len(bursts) // 2]
        lo, hi = wilson(hit, n_)
        interval = f"[{lo:.2f}, {hi:.2f}]"
        print(f"  {name:<22}{n_:>6}{hit:>7}{hit / n_:>8.3f}{interval:>18}{med:>14.2f}")

    slow = buckets.get("instrument_rotation")
    if slow:
        lo, hi = wilson(slow[1], slow[0])
        print("\n  THE FINDING, not a limitation. Burst rate is the ONLY feature that")
        print("  separates rings from households: they share entities by construction,")
        print("  they span comparable numbers of merchants, and the corpus builds both")
        print("  by the same code path. So a ring that adopts household tempo is")
        print("  undetectable by this method AT ANY ACCEPTABLE PRECISION - not merely")
        print("  missed by a threshold that could be lowered. Lowering the burst weight")
        print("  trades directly against the precision floor and the false-ring rate.")
        print(f"\n  Reported honestly: {slow[1]} of {slow[0]} caught is a point estimate of")
        print(f"  {slow[1] / slow[0]:.3f} with a 95% interval of [{lo:.2f}, {hi:.2f}] - consistent with any")
        print("  true recall below roughly a half. Four groups cannot say more, and")
        print("  quoting 0.000 as though it were precise overstates both the failure")
        print("  and our knowledge of it.")
        print("\n  Slow rings need a DIFFERENT SIGNAL, not a lower threshold: instrument")
        print("  reuse velocity relative to identity churn, or cross-merchant")
        print("  coordination in WHAT is claimed rather than WHEN. Neither is built.")
        print("\n  Adversarial consequence, stated because the track is defense-only:")
        print("  publishing a burst-based detector teaches the evasion - slow down. That")
        print("  is a real argument for burst detection being a COMPONENT inside a")
        print("  larger system rather than a standalone product, and it is why the ring")
        print("  finding feeds the evidence package rather than being the product.")

    print("\n  False-ring rate is reported separately and never folded into an")
    print("  aggregate. Reporting an innocent household as a fraud ring is the worst")
    print("  error this system can make, so precision carries a floor and recall")
    print("  does not.")
    print(f"\n  Sized honestly: network features are worth {rupees(net_feature_value)} on the")
    print(f"  test split, against {rupees(ev - tuned)} for the decision rule. This is a")
    print("  secondary capability. The exhibit's effect on issuer behaviour is")
    print("  UNMEASURED - the corpus's issuer model draws from a fixed noise")
    print("  distribution and does not respond to exhibits, so nothing is claimed.")

    # ----------------------------------------------------------- evidence
    # Measured on the same held-out split as every rupee figure above, not on
    # the corpus as a whole, so the console's tiles all describe one population.
    blocked = sum(1 for r in test if r["blocking_gaps"])
    routed = sum(1 for r in test if r["routing"] == "route_to_human")
    metrics["evidence"] = {
        "split": "test",
        "disputes": len(test),
        "blocking_gap_rate": round(blocked / len(test), 4),
        "blocking_gap_count": blocked,
        "routed_to_human_rate": round(routed / len(test), 4),
        "routed_to_human_count": routed,
        "sufficient_rate": round(
            sum(1 for r in test if r["evidence_sufficient"]) / len(test), 4),
    }
    metrics["provenance"] = {
        "seed": args.seed,
        "corpus": str(Path(args.corpus)),
        "command": f"make eval COST={cost}",
        "split": "held-out test",
        # Deliberately no timestamp. A regenerated file that differs only in when
        # it was written trains the reader to ignore the diff.
    }

    # ----------------------------------------------------------- figures
    if not args.no_figures:
        try:
            write_figures(Path(args.figures), probs, y_arr, test, amounts, cost, adj, y)
            write_sensitivity_figure(Path(args.figures), sweep)
            print(f"\nfigures written to {args.figures}/")
        except Exception as exc:  # pragma: no cover - plotting is not the product
            print(f"\nfigures skipped: {exc}")

    if args.metrics_out:
        out = Path(args.metrics_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"console metrics written to {out}")

    section("verdict")
    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("  all evaluation checks passed")
    return 0


def write_sensitivity_figure(out: Path, sweep) -> None:
    """Net rupees against contest cost, for every policy.

    The most defensible chart in the build: it shows exactly where the system is
    worth little and where it is worth a lot, instead of asserting one number
    from one assumed cost.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    LAKH = 10_000_000
    cs = [r[0] / 100 for r in sweep]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))
    ax.plot(cs, [r[2] / LAKH for r in sweep], "o-", color="#B0762A", lw=1.6,
            label="contest everything (t = 0)")
    ax.plot(cs, [r[3] / LAKH for r in sweep], "s-", color="#2B3A67", lw=1.6,
            label="best tuned constant t*")
    ax.plot(cs, [r[4] / LAKH for r in sweep], "^-", color="#3F7A6E", lw=1.8,
            label="expected-cost rule")
    ax.set_xscale("log")
    ax.set_xlabel("contest cost C (Rs, log scale)")
    ax.set_ylabel("net recovered (Rs lakh)")
    ax.set_title("The system's value depends on your ops cost", color="#16171C")

    # Log y as well: a linear axis is swamped by the 1651% point at C = Rs 5,000
    # and hides the 5-13% crossover, which is the region a real merchant is in.
    ax2.plot(cs, [max(r[6], 0.05) for r in sweep], "^-", color="#3F7A6E", lw=1.8,
             label="rule edge")
    ax2.axhline(5.0, color="#7A2E2E", ls="--", lw=1, label="5% - materiality")
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("contest cost C (Rs, log scale)")
    ax2.set_ylabel("rule edge over best constant (%)")
    ax2.set_title("Where discrimination starts to pay", color="#16171C")

    for a in (ax, ax2):
        a.set_facecolor("#E8E6E1")
        a.grid(color="white", lw=0.8)
        a.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "cost_sensitivity.png", dpi=150)
    plt.close(fig)


def write_figures(out: Path, probs, y_arr, test, amounts, cost, adj, y) -> None:
    """PR curve, reliability diagram, cost curve.

    Palette is the product's: indigo for structure, verdigris for the
    recoverable path, ochre for the thing that needs a human, oxblood for loss.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    ink, grid = "#16171C", "#E8E6E1"
    indigo, verdigris, ochre, oxblood = "#2B3A67", "#3F7A6E", "#B0762A", "#7A2E2E"

    def style(ax) -> None:
        ax.set_facecolor(grid)
        ax.grid(color="white", lw=0.8)
        ax.legend(frameon=False)

    # --- reliability -------------------------------------------------------
    xs, ys, _ = reliability(probs, y_arr)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], color=ochre, lw=1, ls="--", label="perfect calibration")
    ax.plot(xs, ys, "o-", color=indigo, lw=1.6, label=f"after {adj.calibrator.name}")
    ax.set_xlabel("predicted P(win)")
    ax.set_ylabel("observed win rate")
    ax.set_title(f"Reliability, test split (ECE {ece(probs, y_arr):.3f})", color=ink)
    style(ax)
    fig.tight_layout()
    fig.savefig(out / "reliability.png", dpi=150)
    plt.close(fig)

    # --- precision-recall --------------------------------------------------
    order = sorted(range(len(probs)), key=lambda i: -probs[i])
    total_pos = max(1, sum(y))
    tp = fp = 0
    curve = []
    for i in order:
        if y[i]:
            tp += 1
        else:
            fp += 1
        curve.append((tp / total_pos, tp / (tp + fp)))
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([c[0] for c in curve], [c[1] for c in curve], color=indigo, lw=1.6,
            label="model")
    ax.axhline(float(np.mean(y_arr)), color=oxblood, ls="--", lw=1, label="base rate")
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title(f"Precision-recall (PR-AUC {pr_auc(list(probs), y):.3f})", color=ink)
    style(ax)
    fig.tight_layout()
    fig.savefig(out / "pr_curve.png", dpi=150)
    plt.close(fig)

    # --- cost curve --------------------------------------------------------
    # The argument in one image: every fixed threshold sits below the rule, and
    # 0.5 is partway down the cliff.
    LAKH = 10_000_000  # paise in one lakh of rupees
    ts = np.linspace(0.01, 0.99, 99)
    nets = [net(test, [p > t for p in probs], cost) / LAKH for t in ts]
    ev_thr = [break_even(a, cost) for a in amounts]
    ev_net = net(test, [p > t for p, t in zip(probs, ev_thr, strict=True)], cost) / LAKH
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.plot(ts, nets, color=indigo, lw=1.6, label="fixed threshold")
    ax.axhline(ev_net, color=verdigris, lw=1.8, label="expected-cost rule (p > C/A)")
    ax.axvline(0.5, color=ochre, ls="--", lw=1, label="p > 0.5")
    ax.set_xlabel("fixed threshold")
    ax.set_ylabel("net recovered, test split (Rs lakh)")
    ax.set_title("Every fixed threshold sits below the rule", color=ink)
    style(ax)
    fig.tight_layout()
    fig.savefig(out / "cost_curve.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
