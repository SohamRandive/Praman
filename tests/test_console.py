"""The console renders the decision. It must not reinterpret or soften it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from praman.console import countdown, rupees

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "web" / "src" / "cases.json"


@pytest.fixture(scope="module")
def cases():
    if not CASES.exists():
        pytest.skip("fixtures not generated; run `make console-data`")
    with open(CASES, encoding="utf-8") as fh:
        return json.load(fh)


def test_amounts_use_indian_digit_grouping_and_are_never_abbreviated():
    """A finance reader reads 18,400. Nothing in a decision context is shortened
    to "18.4k" - a merchant cannot reconcile an abbreviation."""
    assert rupees(1_840_000) == "₹18,400"
    assert rupees(312_706_900) == "₹31,27,069"
    assert rupees(26_300) == "₹263"
    assert "k" not in rupees(5_000_000).lower()


def test_the_deadline_is_computed_and_graded_by_proximity():
    """Three bands, not two: critical inside a day, at risk inside three, calm
    beyond. The dial reads the same gradient, so the bands and the colour are
    driven by one number rather than drifting apart."""
    calm = countdown("2026-03-20T00:00:00+05:30", "2026-03-08T00:00:00+05:30")
    assert calm["display"] == "12d 00h"
    assert not calm["at_risk"] and not calm["critical"]

    risky = countdown("2026-03-10T00:00:00+05:30", "2026-03-08T00:00:00+05:30")
    assert risky["at_risk"] and not risky["critical"]

    urgent = countdown("2026-03-08T18:00:00+05:30", "2026-03-08T00:00:00+05:30")
    assert urgent["critical"] and not urgent["expired"]

    gone = countdown("2026-03-01T00:00:00+05:30", "2026-03-08T00:00:00+05:30")
    assert gone["expired"] and gone["display"] == "expired"


def test_the_dial_depletes_against_this_codes_own_filing_window():
    """A bare countdown cannot express that seven days half gone is tighter than
    twenty-one days half gone. `elapsed` is what the arc renders, and it is
    relative to the window this reason code actually grants."""
    half = countdown(
        respond_by="2026-03-15T00:00:00+05:30",
        now="2026-03-08T00:00:00+05:30",
        created_at="2026-03-01T00:00:00+05:30",
    )
    assert half["window_hours"] == pytest.approx(14 * 24)
    assert half["elapsed"] == pytest.approx(0.5, abs=1e-3)

    fresh = countdown("2026-03-15T00:00:00+05:30", "2026-03-01T00:00:00+05:30",
                      "2026-03-01T00:00:00+05:30")
    assert fresh["elapsed"] == 0.0
    assert countdown("2026-03-01T00:00:00+05:30", "2026-03-20T00:00:00+05:30",
                     "2026-03-01T00:00:00+05:30")["elapsed"] == 1.0


def test_the_demo_clock_is_stable_and_inside_the_window():
    """The simulated present must be reproducible, or the queue reshuffles on
    every regeneration and no screenshot survives."""
    from praman.console.serialize import observation_time

    args = ("disp_AHfqOvkldwsbqt", "2026-03-01T00:00:00+05:30", "2026-03-15T00:00:00+05:30")
    assert observation_time(*args) == observation_time(*args)
    assert args[1] < observation_time(*args) < args[2]
    others = {observation_time(f"disp_{i}", args[1], args[2]) for i in range(12)}
    assert len(others) > 8, "the demo clock barely varies; the queue reads as uniform"


def test_every_case_carries_the_five_stages_the_trace_renders(cases):
    """The content model is `make trace`. No new information architecture."""
    for c in cases:
        assert c["reason_code"] and c["title"], c["dispute_id"]        # resolve
        assert c["evidence"]["checklist"]                              # bind
        assert "completeness" in c["evidence"]                         # score
        assert isinstance(c["constraints"], list)                      # constrain
        assert c["evidence"]["routing"]                                # assemble
        assert c["recommendation"]["rationale"]
        assert c["deadline"]["display"]


def test_the_console_shows_the_exception_list_rather_than_hiding_it(cases):
    """Blocked packages, degraded agents and routed cases are the product. A
    console that only renders the happy path hides what the merchant must act
    on."""
    assert any(not c["evidence"]["sufficient"] for c in cases), "no blocked case shown"
    assert any(c["evidence"]["gaps"] for c in cases), "no named gap shown"
    assert any(a["status"] != "ok" for c in cases for a in c["agents"]), "no degradation shown"
    assert any(c["recommendation"]["action"] == "accept" for c in cases)
    assert any(c["recommendation"]["action"] == "contest" for c in cases)


def test_blocked_cases_give_an_instruction_not_a_mood(cases):
    for c in cases:
        for gap in c["evidence"]["gaps"]:
            name = gap if isinstance(gap, str) else gap["name"]
            assert name.strip() and name[0].isupper(), c["dispute_id"]
            assert "artifact." not in name, "a predicate detail reached the screen"


def test_break_even_is_shown_alongside_the_probability(cases):
    """The decision is `p > C/A`. Showing p without the threshold it is compared
    against would make the recommendation unauditable by the person acting on it."""
    for c in cases:
        r = c["recommendation"]
        assert 0.0 <= r["p_win"] <= 1.0
        assert 0.0 < r["break_even"] <= 1.0
        assert (r["action"] == "contest") == (
            r["p_win"] > r["break_even"] and c["evidence"]["sufficient"]
        ), c["dispute_id"]


def test_the_audit_chain_is_reported_intact_for_every_case(cases):
    for c in cases:
        assert c["audit_intact"], c["dispute_id"]
        assert c["audit"][0]["event"] == "dispute.created"
        assert c["audit"][-1]["event"] == "decision.made"


def test_no_case_carries_a_ground_truth_field_to_the_screen(cases):
    """The console shows what the system knew, not what the corpus knows."""
    blob = json.dumps(cases)
    for banned in ("gt_winnable", "gt_merchant_at_fault", "observed_won", "gt_in_abusive_ring"):
        assert banned not in blob, f"{banned} reached the console"


def test_the_queue_spans_real_urgency_rather_than_twelve_fresh_cases(cases):
    """The rail's whole job is letting someone judge twelve cases in a second.
    That only works if they actually differ."""
    elapsed = sorted(c["deadline"]["elapsed"] for c in cases)
    assert elapsed[0] < 0.25 and elapsed[-1] > 0.7, elapsed
    windows = {round(c["deadline"]["window_hours"] / 24) for c in cases}
    assert len(windows) >= 4, "every case has the same filing window"


def test_the_console_lands_on_the_most_instructive_case(cases):
    """A clean contest with nothing firing and five green agents teaches
    nothing. The WhatsApp refusal is the product thesis, and one agent is down
    so partial-failure survival is visible without hunting for it.

    Since ADR-013 the console opens on the queue rather than on a case, so this
    is the case the shell has SELECTED - the one the case view and the audit
    trail open on, and the one a demo reaches first."""
    first = cases[0]
    assert any(r["constraint_id"] == "email_channel_only" for r in first["rejections"])
    assert not first["evidence"]["sufficient"]
    assert any(a["status"] != "ok" for a in first["agents"]), "no degradation on landing"
    assert first["recommendation"]["rationale"]


# --------------------------------------------------------------- KPI numbers


METRICS = ROOT / "web" / "src" / "metrics.json"


@pytest.fixture(scope="module")
def metrics():
    if not METRICS.exists():
        pytest.skip("metrics not generated; run `make console-metrics`")
    with open(METRICS, encoding="utf-8") as fh:
        return json.load(fh)


def test_every_kpi_the_console_reads_is_present_and_measured(metrics):
    """The KPI strip is not allowed a placeholder. Every tile on the landing
    screen resolves to one of these keys, so a missing key is a blank tile and a
    zero here is a number nobody measured."""
    econ, rings, ev = metrics["economics"], metrics["rings"], metrics["evidence"]
    assert econ["test_disputes"] > 0 and econ["test_merchants"] > 0
    assert econ["cost_minor"] > 0
    assert 0.0 < rings["precision"] <= 1.0
    assert 0.0 <= rings["false_ring_rate"] < 1.0
    assert rings["decoys"] > 0, "a false-ring rate with no denominator says nothing"
    assert 0.0 < ev["blocking_gap_rate"] < 1.0
    assert metrics["provenance"]["seed"] and metrics["provenance"]["split"]

    keys = {p["key"] for p in econ["policies"]}
    # The exact set CaseQueue.jsx renders in its ledger.
    assert {"accept_all", "contest_all", "naive_half",
            "best_constant", "expected_cost_rule"} <= keys


def test_the_rule_beats_every_baseline_in_the_numbers_the_console_shows(metrics):
    """The console renders the policy table as the headline. If the ordering ever
    inverted, the screen would still render it - so it is asserted here rather
    than trusted to be noticed."""
    by_key = {p["key"]: p for p in metrics["economics"]["policies"]}
    rule = by_key["expected_cost_rule"]["net_minor"]
    for base in ("accept_all", "contest_all", "naive_half", "best_constant"):
        assert rule > by_key[base]["net_minor"], base


def test_the_headline_delta_is_against_the_tuned_constant_not_against_half(metrics):
    """ADR-012. Contest-everything is itself a constant threshold at t = 0, so
    only the tuned constant tests the rule's actual claim. The console must lead
    with the smaller, honest figure, so the two are kept distinct in the export
    and each is checked against the row it is derived from."""
    by_key = {p["key"]: p for p in metrics["economics"]["policies"]}
    econ = metrics["economics"]
    rule = by_key["expected_cost_rule"]["net_minor"]
    assert econ["rule_vs_best_constant_minor"] == rule - by_key["best_constant"]["net_minor"]
    assert econ["rule_vs_naive_half_minor"] == rule - by_key["naive_half"]["net_minor"]
    assert econ["rule_vs_best_constant_minor"] < econ["rule_vs_naive_half_minor"], (
        "the weaker comparison is not larger - check which one the console leads with"
    )


def test_money_reaching_the_console_is_formatted_once_in_python(metrics):
    """Indian digit grouping and the rupee glyph, produced by one function. A
    second implementation in JavaScript is a second thing that can disagree with
    the ledger."""
    for p in metrics["economics"]["policies"]:
        assert p["net"].lstrip("-").startswith("₹"), p["key"]
        assert "k" not in p["net"].lower(), "an amount was abbreviated"
    assert rupees(metrics["economics"]["policies"][1]["net_minor"]) == \
        metrics["economics"]["policies"][1]["net"]


def test_the_console_never_claims_the_drafting_model_exists(metrics):
    """Phase 6 is not built. The sidebar says so, and the fixture payloads carry
    an empty summary rather than a plausible sentence."""
    src = (ROOT / "web" / "src" / "Sidebar.jsx").read_text(encoding="utf-8")
    assert "not built" in src, "the sidebar no longer states the Phase 6 gap"
