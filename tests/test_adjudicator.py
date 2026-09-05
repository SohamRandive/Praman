"""The money rule, the leakage guard, and the calibration protocol.

These are the tests that stop a wrong rupee figure reaching a merchant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from praman.adjudicator import LeakageError, break_even, decide, expected_value, guard
from praman.adjudicator.features import extract, spec

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus" / "disputes.jsonl"


@pytest.fixture(scope="module")
def rows():
    if not CORPUS.exists():
        pytest.skip("corpus not generated; run `make data`")
    with open(CORPUS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


# ------------------------------------------------------------------ leakage


def test_guard_refuses_every_ground_truth_column(rows):
    gt = [k for k in rows[0] if k.startswith("gt_")]
    assert gt, "corpus has no ground-truth columns to guard against"
    for column in gt:
        with pytest.raises(LeakageError, match="evaluation-only"):
            guard([column])


def test_guard_refuses_the_training_label():
    with pytest.raises(LeakageError):
        guard(["observed_won"])


def test_the_extracted_feature_set_contains_no_label(rows):
    names = set(extract(rows[0]))
    assert not {n for n in names if n.startswith("gt_")}
    assert "observed_won" not in names
    guard(spec(rows).names)  # must not raise


def test_a_new_ground_truth_column_is_refused_automatically():
    """The guard is a prefix rule, not a hand-maintained list, so a column added
    to the generator tomorrow is refused without anyone remembering to add it."""
    with pytest.raises(LeakageError):
        guard(["gt_some_column_invented_later"])


# --------------------------------------------------------------- the money rule


@pytest.mark.parametrize(
    "rupees,expected",
    [(500, 0.70), (2_000, 0.175), (18_400, 0.019), (50_000, 0.007)],
)
def test_break_even_is_a_function_of_the_amount(rupees, expected):
    """The whole thesis: the threshold moves with the amount. At Rs 350 cost a
    Rs 500 dispute needs p > 0.70; a Rs 50,000 dispute needs p > 0.007."""
    assert break_even(rupees * 100) == pytest.approx(expected, abs=5e-4)


def test_a_dispute_worth_less_than_the_contest_cost_is_never_worth_contesting():
    assert break_even(20_000, 35_000) == 1.0
    assert decide(0.999, 20_000).action == "accept"


def test_expected_value_matches_the_stated_arithmetic():
    # p*A - C, with A = Rs 18,400 and C = Rs 350
    assert expected_value(0.83, 1_840_000, 35_000) == round(0.83 * 1_840_000 - 35_000)


def test_the_rule_contests_above_break_even_and_accepts_below():
    assert decide(0.02, 1_840_000).action == "contest"   # threshold 0.019
    assert decide(0.01, 1_840_000).action == "accept"


def test_an_unassemblable_package_is_accepted_however_good_the_odds():
    """Not a probability judgement - a fact about record-keeping. Contesting
    without the required evidence spends the cost to lose the same amount."""
    d = decide(0.99, 5_000_000, evidence_sufficient=False,
               blocking_gaps=("No proof of delivery.",))
    assert d.action == "accept"
    assert d.overrides == ("evidence_insufficient",)
    assert "No proof of delivery." in d.rationale


def test_the_rationale_is_templated_and_every_number_traceable():
    d = decide(0.83, 1_840_000, comparable=(34, 41))
    for fragment in ("Contest.", "34 of 41 won", "P(win) 0.83", "Rs 18,400",
                     "Rs 350", "break-even probability is 0.019"):
        assert fragment in d.rationale, d.rationale


def test_the_rule_can_recommend_accepting():
    """A risk tool that can only ever say fight is a sales tool."""
    assert decide(0.10, 60_000).action == "accept"


# ----------------------------------------------------------------- the model


@pytest.mark.slow
def test_model_is_deterministic_and_stays_under_the_corpus_ceiling(rows):
    from eval.metrics import auc
    from praman.adjudicator.model import train

    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["split"], []).append(r)

    a = train(by["train"], by["calibration"], seed=20260904)
    b = train(by["train"], by["calibration"], seed=20260904)
    pa, pb = a.predict(by["test"]), b.predict(by["test"])
    assert list(pa) == list(pb), "training is not deterministic at a fixed seed"
    assert a.calibrator.name == b.calibrator.name

    y = [r["observed_won"] for r in by["test"]]
    score = auc(list(pa), y)
    # 0.897 is this corpus's ceiling, set by issuer noise. Above it is a leak.
    assert score <= 0.897, f"AUC {score:.4f} exceeds the corpus ceiling - check for a leak"
    assert score > 0.65, f"AUC {score:.4f} is too low to be a working model"


@pytest.mark.slow
def test_the_calibrator_is_chosen_without_ever_seeing_the_test_split(rows):
    from praman.adjudicator.model import train

    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["split"], []).append(r)
    adj = train(by["train"], by["calibration"])
    sc = adj.calibration_scores
    assert set(sc["mean_ece"]) == {"none", "sigmoid", "isotonic"}
    assert sc["selected"] in sc["mean_ece"]
    # The one-standard-error rule must never pick something worse than the cutoff.
    assert sc["mean_ece"][sc["selected"]] <= sc["one_se_cutoff"] + 1e-9
