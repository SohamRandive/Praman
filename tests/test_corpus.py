"""Generator properties that must hold for any number derived from the corpus."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "data" / "generator" / "build.py"


def digest(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()


def generate(out: Path, seed: int, n: int = 600) -> None:
    result = subprocess.run(
        [sys.executable, str(BUILD), "--out", str(out), "--seed", str(seed),
         "--target-disputes", str(n)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def twin(tmp_path_factory) -> tuple[Path, Path]:
    a = tmp_path_factory.mktemp("run_a")
    b = tmp_path_factory.mktemp("run_b")
    generate(a, 20260904)
    generate(b, 20260904)
    return a, b


FILES = ("disputes.jsonl", "merchants.jsonl", "groups.jsonl", "entity_edges.jsonl")


@pytest.mark.parametrize("name", FILES)
def test_corpus_is_bit_reproducible_from_a_seed(twin, name):
    """Every number in the README has to survive a clean checkout. If the
    generator is not bit-stable, none of them do."""
    a, b = twin
    assert digest(a / name) == digest(b / name), f"{name} differs between runs"


def test_a_different_seed_gives_a_different_corpus(tmp_path):
    """Guards against a seed that is accepted and then ignored."""
    other = tmp_path / "other"
    generate(other, 999)
    rows = [json.loads(x) for x in (other / "disputes.jsonl").read_text().splitlines()]
    assert len(rows) > 100
    ids = {r["dispute_id"] for r in rows}
    assert len(ids) == len(rows), "dispute ids are not unique"


def test_no_ground_truth_column_is_reachable_as_a_feature():
    """Hard rule: anything prefixed gt_ is evaluation-only. One leaked column
    invalidates every number downstream, and it is the easiest mistake to make.
    The allowlist is enforced here rather than trusted."""
    from eval.validate_corpus import CANDIDATE_FEATURES

    leaked = {k for k in CANDIDATE_FEATURES if k.startswith("gt_")}
    assert not leaked, f"ground-truth columns in the feature allowlist: {leaked}"
    assert "observed_won" not in CANDIDATE_FEATURES, "the training label is a feature"


def test_ground_truth_columns_exist_and_are_clearly_marked(twin):
    a, _ = twin
    row = json.loads((a / "disputes.jsonl").read_text().splitlines()[0])
    gt = {k for k in row if k.startswith("gt_")}
    assert gt >= {"gt_winnable", "gt_merchant_at_fault"}, gt
    assert "observed_won" in row


def test_ground_truth_is_factored_not_asserted(twin):
    """gt_winnable must equal (not merchant_at_fault) and evidence_sufficient,
    row for row. If the halves ever stop being independent inputs, the corpus
    has started asserting its own label."""
    a, _ = twin
    rows = [json.loads(x) for x in (a / "disputes.jsonl").read_text().splitlines()]
    for r in rows:
        expected = (not r["gt_merchant_at_fault"]) and r["evidence_sufficient"]
        assert r["gt_winnable"] == expected, r["dispute_id"]


def test_no_raw_identifier_leaves_the_generator(twin):
    """All identity joins are on salted hashes. Nothing here may be invertible
    to a real person, and no PAN exists anywhere in the system."""
    a, _ = twin
    text = (a / "entity_edges.jsonl").read_text()
    assert "@" not in text, "an email-shaped value reached the entity graph"
    for row in (json.loads(x) for x in text.splitlines()):
        assert row["src"].startswith("ide_")
        assert row["dst_kind"] in {"device", "address_geo", "instrument"}

    disputes = (a / "disputes.jsonl").read_text().lower()
    # Word-bounded: a bare "pan" substring also matches "merchant_span", which
    # made an earlier version of this guard fail on its own field names.
    banned = re.compile(r"\b(card_number|pan|cvv|card_pan|aadhaar)\b|@gmail|\+91\d")
    hit = banned.search(disputes)
    assert not hit, f"{hit.group(0)!r} reached the corpus"


def test_groups_never_span_a_split(twin):
    """A ring spanning train and test would leak its structure across the
    boundary and make test-split ring recall meaningless."""
    a, _ = twin
    rows = [json.loads(x) for x in (a / "disputes.jsonl").read_text().splitlines()]
    per_group: dict[str, set[str]] = {}
    for r in rows:
        if r["group_id"]:
            per_group.setdefault(r["group_id"], set()).add(r["split"])
    offenders = {g: s for g, s in per_group.items() if len(s) > 1}
    assert not offenders, f"groups spanning splits: {offenders}"


@pytest.mark.parametrize("n", [12, 14, 20, 7])
def test_allocate_matches_the_requested_ratios_at_awkward_counts(n):
    """Largest-remainder allocation is DORMANT at the current 20 merchants per
    archetype, where 60/15/25 divides evenly and naive flooring gives the same
    answer. A dormant guard with no test silently stops working, so it is tested
    at counts where it actually does something.
    """
    from data.generator.build import allocate

    ratios = {"train": 0.60, "calibration": 0.15, "test": 0.25}
    got = allocate(n, ratios)
    assert sum(got.values()) == n, "allocation must be exhaustive"
    assert all(v >= 0 for v in got.values())
    # Every split within one of its exact share - the property flooring breaks.
    for split, ratio in ratios.items():
        assert abs(got[split] - n * ratio) < 1.0, f"{split} off by more than one"


def test_allocate_beats_naive_flooring_where_flooring_starves_a_split():
    """The concrete failure this guard exists for: with 12 merchants per
    archetype, int(12 * 0.15) == 1, which starved the calibration split."""
    from data.generator.build import allocate

    ratios = {"train": 0.60, "calibration": 0.15, "test": 0.25}
    naive = {k: int(12 * v) for k, v in ratios.items()}
    assert sum(naive.values()) == 11, "flooring should lose a merchant here"
    assert naive["calibration"] == 1
    assert allocate(12, ratios)["calibration"] == 2
    assert sum(allocate(12, ratios).values()) == 12
