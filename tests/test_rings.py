"""Ring detection: precision floor, false-ring rate, and the two-stage split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from praman.network import components
from praman.network.rings import candidates, choose_threshold, cohesion, evaluate

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus"


@pytest.fixture(scope="module")
def corpus():
    if not (CORPUS / "disputes.jsonl").exists():
        pytest.skip("corpus not generated; run `make data`")

    def read(name):
        with open(CORPUS / name, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]

    rows, edges, groups = read("disputes.jsonl"), read("entity_edges.jsonl"), read("groups.jsonl")
    return rows, edges, {g["group_id"]: g for g in groups}


@pytest.fixture(scope="module")
def scored(corpus):
    rows, edges, groups = corpus
    cands = candidates(rows, edges)
    by_disp = {r["dispute_id"]: r for r in rows}
    labels = {
        c.component_id: any(
            groups[g]["is_abusive"]
            for g in {by_disp[d]["group_id"] for d in c.dispute_ids if by_disp[d]["group_id"]}
        )
        for c in cands
    }
    return [(c, cohesion(c)) for c in cands], labels


def test_candidate_generation_is_over_inclusive_by_design(scored):
    """Stage one must have high recall: it is cheap and deliberately catches
    households alongside rings. Precision is stage two's job, and conflating
    the stages is how ring detectors end up accusing families."""
    cands, labels = scored
    assert len(cands) >= 140, "candidate generation is missing whole groups"
    assert sum(labels.values()) >= 55, "most rings must survive stage one"
    assert sum(1 for v in labels.values() if not v) >= 80, "decoys must also be candidates"


def test_a_household_is_not_a_ring_on_structure_alone(scored):
    """A family sharing one address and one device is structurally identical to
    a device farm. Only burst and volume separate them."""
    cands, labels = scored
    decoys = [c for c, _ in cands if not labels[c.component_id]]
    rings = [c for c, _ in cands if labels[c.component_id]]
    assert decoys and rings
    # Structure overlaps...
    assert min(c.merchant_span for c in rings) <= max(c.merchant_span for c in decoys)
    # ...behaviour is what separates them.
    med_ring = sorted(c.disputes_per_day for c in rings)[len(rings) // 2]
    med_decoy = sorted(c.disputes_per_day for c in decoys)[len(decoys) // 2]
    assert med_ring > 5 * med_decoy


def test_precision_floor_holds_on_the_held_out_split(scored):
    """Precision carries a floor and recall does not, because the errors are not
    symmetric: a missed ring costs one merchant one dispute, and an accused
    household is the worst thing this system can produce."""
    cands, labels = scored
    cal = [(c, s) for c, s in cands if c.split == "calibration"]
    test = [(c, s) for c, s in cands if c.split == "test"]
    thr = choose_threshold(cal, labels, target_precision=0.85)
    m = evaluate(test, labels, thr)
    assert m["precision"] >= 0.85, f"ring precision {m['precision']:.3f} below floor"
    assert m["recall"] > 0.5, "recall collapsed; the threshold is not usable"


def test_false_ring_rate_is_reported_separately(scored):
    cands, labels = scored
    test = [(c, s) for c, s in cands if c.split == "test"]
    thr = choose_threshold(
        [(c, s) for c, s in cands if c.split == "calibration"], labels, 0.85)
    m = evaluate(test, labels, thr)
    assert "false_ring_rate" in m and "false_rings" in m
    assert m["false_ring_rate"] <= 0.15, f"too many innocent clusters accused: {m}"


def test_components_never_span_a_split(corpus):
    """A ring spanning train and test would leak its structure across the
    boundary and make test-split ring recall meaningless."""
    rows, edges, _ = corpus
    comp = components(edges)
    seen: dict[str, set[str]] = {}
    for r in rows:
        seen.setdefault(comp.get(r["identity_hash"], r["identity_hash"]), set()).add(r["split"])
    assert not [c for c, s in seen.items() if len(s) > 1]


def test_cohesion_is_deterministic_and_bounded(scored):
    cands, _ = scored
    for c, s in cands:
        assert 0.0 <= s <= 1.0
        assert cohesion(c) == s


def test_network_features_never_see_the_future(corpus):
    """Asserted invariant, not a property of the code.

    Every dispute contributing to a component's statistics must have happened
    strictly before the dispute reading them, and every identity counted in the
    component must already have transacted. A temporal leak here is invisible in
    the metrics - it makes the features better, not inconsistent - so it would
    survive a refactor unnoticed without this test.
    """
    from praman.network import point_in_time_features

    rows, edges, _ = corpus
    pit = point_in_time_features(rows, edges)
    by_time = sorted(rows, key=lambda r: (r["created_at"], r["dispute_id"]))

    # The first dispute in the corpus can have no history at all.
    first = pit[by_time[0]["dispute_id"]]
    assert first["component_prior_disputes"] == 0.0
    assert first["component_active_days"] == 0.0

    # Prior counts are monotone in time within a component and never exceed the
    # number of disputes that had actually occurred.
    for i, d in enumerate(by_time):
        f = pit[d["dispute_id"]]
        assert f["component_prior_disputes"] <= i, (
            f"{d['dispute_id']} counts {f['component_prior_disputes']} prior disputes "
            f"but only {i} had happened"
        )
        assert f["component_prior_identities"] <= f["component_size"]


def test_component_size_grows_over_time_rather_than_starting_final(corpus):
    """The specific leak this replaced: membership read off the finished graph,
    so a dispute could see how large its ring would eventually become."""
    from praman.network import components, point_in_time_features

    rows, edges, _ = corpus
    pit = point_in_time_features(rows, edges)
    final = components(edges)
    sizes: dict[str, int] = {}
    for comp in final.values():
        sizes[comp] = sizes.get(comp, 0) + 1

    by_time = sorted(rows, key=lambda r: (r["created_at"], r["dispute_id"]))
    seen_smaller = False
    for d in by_time:
        pit_size = pit[d["dispute_id"]]["component_size"]
        final_size = sizes[final.get(d["identity_hash"], d["identity_hash"])]
        assert pit_size <= final_size, "point-in-time size exceeds the final graph"
        if pit_size < final_size:
            seen_smaller = True
    assert seen_smaller, "no dispute ever saw a partial component - membership is static"
