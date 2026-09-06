"""Phase 5: the contract, partial failure, idempotency, and the audit chain.

`test_decision_survives_each_agent_failure` is the "one failure handled
gracefully" evidence, made architectural rather than anecdotal. It is
parameterised over all five agents and cited by name in the video.
"""

from __future__ import annotations

import asyncio
import collections
import json
from pathlib import Path

import pytest

from praman.agents import (
    EvidenceRetrieval,
    MerchantContext,
    NetworkForensics,
    PolicyCompliance,
    PrecedentRecall,
)
from praman.audit import GENESIS, AuditLog
from praman.evidence import ReasonCodeMatrix
from praman.network import point_in_time_features
from praman.orchestrator import AgentResult, CaseFile, case_id_for, deadline_budget, guarded
from praman.orchestrator.orchestrate import run_case

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus"
AGENT_NAMES = ["evidence", "network", "precedent", "policy", "merchant"]


@pytest.fixture(scope="module")
def wired():
    if not (CORPUS / "disputes.jsonl").exists():
        pytest.skip("corpus not generated; run `make data`")

    def read(name):
        with open(CORPUS / name, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]

    rows, edges = read("disputes.jsonl"), read("entity_edges.jsonl")
    merchants = {m["merchant_id"]: m for m in read("merchants.jsonl")}
    comps = point_in_time_features(rows, edges)
    hist = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r["split"] == "train":
            k = (r["reason_code"], bool(r["no_blocking_gaps"]))
            hist[k][1] += 1
            hist[k][0] += int(r["observed_won"])
    agents = [
        EvidenceRetrieval(ReasonCodeMatrix.load()),
        NetworkForensics(comps),
        PrecedentRecall({k: tuple(v) for k, v in hist.items()}),
        PolicyCompliance(),
        MerchantContext(merchants),
    ]
    row = next(
        r for r in rows
        if r["split"] == "test" and r["amount_minor"] > 500_000 and r["evidence_sufficient"]
    )
    return agents, row


class Dead:
    """An agent whose source is down. Raises, as a real one would."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, case, budget_ms):
        raise RuntimeError(f"{self.name} source unavailable")


class Hung:
    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, case, budget_ms):
        await asyncio.sleep(30)


# ------------------------------------------------- the headline failure test


@pytest.mark.parametrize("victim", AGENT_NAMES)
def test_decision_survives_each_agent_failure(wired, victim):
    """Kill any single agent and the system still produces a decision, with the
    degradation visible in the output. This is the requirement made
    architectural: partial failure is the default path, not an error path."""
    agents, row = wired
    subset = [Dead(a.name) if a.name == victim else a for a in agents]
    case = asyncio.run(run_case(CaseFile.from_row(row), subset, p_win=0.72))

    assert case.decision is not None, f"killing {victim} produced no decision"
    assert case.decision.action in ("contest", "accept")
    assert victim in case.degraded_agents, "degradation was not surfaced"
    assert case.agent_results[victim].status == "failed"
    assert case.agent_results[victim].errors, "a failure with no recorded reason"
    assert not case.audit.verify(), "the audit chain broke under failure"


@pytest.mark.parametrize("victim", AGENT_NAMES)
def test_a_hung_agent_times_out_rather_than_hanging_the_case(wired, victim):
    agents, row = wired
    subset = [Hung(a.name) if a.name == victim else a for a in agents]
    case = asyncio.run(run_case(CaseFile.from_row(row), subset, p_win=0.72))
    assert case.agent_results[victim].status == "timeout"
    assert case.decision is not None


def test_losing_evidence_retrieval_forces_accept_rather_than_filing_blind(wired):
    """The one agent whose loss is not survivable as a contest. Without it we
    cannot know whether a package can be assembled, and filing blind spends the
    contest cost to lose the same money."""
    agents, row = wired
    subset = [Dead("evidence") if a.name == "evidence" else a for a in agents]
    case = asyncio.run(run_case(CaseFile.from_row(row), subset, p_win=0.99))
    assert case.decision.action == "accept"
    assert "could not be retrieved" in case.decision.rationale


def test_degradation_widens_uncertainty_rather_than_being_absorbed(wired):
    """Silent degradation in a money system is the failure mode that ends
    careers. A decision on fewer sources must move toward the base rate."""
    agents, row = wired
    full = asyncio.run(run_case(CaseFile.from_row(row), agents, p_win=0.90))
    partial = asyncio.run(run_case(
        CaseFile.from_row(row),
        [Dead(a.name) if a.name in ("network", "precedent") else a for a in agents],
        p_win=0.90,
    ))
    assert partial.decision.p_win < full.decision.p_win
    assert abs(partial.decision.p_win - 0.5) < abs(full.decision.p_win - 0.5)


def test_every_agent_can_fail_at_once_and_a_decision_still_lands(wired):
    agents, row = wired
    case = asyncio.run(run_case(
        CaseFile.from_row(row), [Dead(a.name) for a in agents], p_win=0.72))
    assert case.decision is not None
    assert case.degraded_agents == sorted(AGENT_NAMES)
    assert not case.audit.verify()


# ------------------------------------------------------------ the contract


def test_guarded_never_lets_an_agent_raise_into_the_orchestrator():
    for bad in (Dead("x"), Hung("x")):
        result = asyncio.run(guarded(bad, None, budget_ms=120))
        assert isinstance(result, AgentResult)
        assert result.status in ("failed", "timeout")
        assert not result.usable


def test_a_contract_violation_is_a_failure_not_something_to_paper_over():
    class WrongType:
        name = "policy"

        async def run(self, case, budget_ms):
            return {"not": "an AgentResult"}

    result = asyncio.run(guarded(WrongType(), None, 500))
    assert result.status == "failed"
    assert "not AgentResult" in result.errors[0]


def test_budgets_are_per_agent_and_tighten_with_the_deadline():
    """A slow graph query must not be able to starve evidence retrieval."""
    roomy = deadline_budget(144, AGENT_NAMES)
    urgent = deadline_budget(3, AGENT_NAMES)
    assert all(urgent[a] < roomy[a] for a in AGENT_NAMES)
    assert roomy["evidence"] > roomy["policy"], "evidence must get the largest share"
    assert all(v >= 150 for v in urgent.values()), "no agent gets an unusable budget"


# ---------------------------------------------------------- idempotency


def test_a_replayed_webhook_resolves_to_the_same_case(wired):
    _, row = wired
    a, b = CaseFile.from_row(row), CaseFile.from_row(row)
    assert a.case_id == b.case_id == case_id_for(row["dispute_id"])
    assert case_id_for("disp_other") != a.case_id


# ------------------------------------------------------------- audit chain


def test_the_audit_chain_is_tamper_evident():
    log = AuditLog()
    assert log.head == GENESIS
    for event in ("dispute.created", "agents.dispatched", "decision.made"):
        log.append("system", event, {"in": 1}, {"out": 2})
    assert not log.verify()

    original = log.records[1]
    log.records[1] = type(original)(**{**original.as_dict(), "event": "tampered"})
    problems = log.verify()
    assert problems, "an edited record went undetected"
    assert "do not match its hash" in problems[0]


def test_every_agent_outcome_is_recorded_including_the_failures(wired):
    agents, row = wired
    case = asyncio.run(run_case(
        CaseFile.from_row(row),
        [Dead("network") if a.name == "network" else a for a in agents], p_win=0.72))
    events = [r.event for r in case.audit.records]
    assert events[0] == "dispute.created"
    # Since Phase 6 the contest path writes `draft.verified` after the decision,
    # so the decision is no longer the last record - only the last one that
    # decides anything.
    assert "decision.made" in events
    assert events[-1] in ("decision.made", "draft.verified")
    actors = {r.actor for r in case.audit.records}
    assert {f"agent:{n}" for n in AGENT_NAMES} <= actors, "an agent left no trace"


# -------------------------------------------------- partial retrieval

def _evidence_case(wired, drop_rate: float, p_win: float = 0.80):
    agents, row = wired
    subset = [
        EvidenceRetrieval(ReasonCodeMatrix.load(), drop_rate=drop_rate)
        if a.name == "evidence" else a
        for a in agents
    ]
    return asyncio.run(run_case(CaseFile.from_row(row), subset, p_win=p_win))


def test_partial_retrieval_scores_what_came_back_not_what_exists(wired):
    """The agent's whole reason for existing. Total failure is the easy case;
    the realistic one is that the courier answers and the support desk does not,
    and the package must be scored on what was actually retrieved. A field the
    merchant has but no source will return today cannot be filed today."""
    clean = _evidence_case(wired, 0.0)
    partial = _evidence_case(wired, 0.35)

    full_payload = clean.agent_results["evidence"].payload
    part_payload = partial.agent_results["evidence"].payload

    assert clean.agent_results["evidence"].status == "ok"
    assert partial.agent_results["evidence"].status == "degraded"
    assert set(part_payload["fields_present"]) < set(full_payload["fields_present"])
    assert part_payload["completeness"] < full_payload["completeness"]
    assert part_payload["unavailable"], "nothing was recorded as unavailable"


def test_partial_retrieval_is_seeded_and_reproducible(wired):
    a = _evidence_case(wired, 0.35).agent_results["evidence"].payload
    b = _evidence_case(wired, 0.35).agent_results["evidence"].payload
    assert a["fields_present"] == b["fields_present"]
    assert a["unavailable"] == b["unavailable"]


def test_a_lost_required_field_produces_a_correctly_named_gap(wired):
    """The merchant must be told which document is missing and why - the source
    did not answer, which is a different problem from never having kept it."""
    case = _evidence_case(wired, 0.7)
    payload = case.agent_results["evidence"].payload
    assert payload["required_coverage"] < 1.0
    gaps = payload["blocking_gaps"]
    assert gaps, "a required field was lost with no gap reported"
    assert any(g.startswith("No ") for g in gaps)
    assert any("source unavailable" in g for g in gaps)
    assert not any("artifact." in g for g in gaps), "a predicate detail reached the merchant"


def test_the_decision_degrades_rather_than_failing(wired):
    """Partial retrieval must never raise, and must never silently return a
    confident answer built on half the evidence."""
    for rate in (0.0, 0.25, 0.5, 0.75, 1.0):
        case = _evidence_case(wired, rate)
        assert case.decision is not None
        assert case.decision.action in ("contest", "accept")
        assert not case.audit.verify()
        # A drop *rate* is not a guarantee: at 0.25 the seeded draw can lose
        # nothing from a three-field case, and reporting "ok" there is correct.
        # What must hold is that degradation is reported whenever it happened.
        payload = case.agent_results["evidence"].payload
        if payload["unavailable"]:
            assert "evidence" in case.degraded_agents
            assert case.agent_results["evidence"].status == "degraded"
        else:
            assert case.agent_results["evidence"].status == "ok"


def test_losing_a_required_field_flips_the_recommendation_to_accept(wired):
    """Contesting without the required document spends the contest cost to lose
    the same money, whatever the probability says."""
    case = _evidence_case(wired, 1.0, p_win=0.99)
    assert case.agent_results["evidence"].payload["required_coverage"] == 0.0
    assert case.decision.action == "accept"


def test_p_shrinks_toward_the_base_rate_in_proportion_to_what_was_lost(wired):
    """Not a flat penalty: an agent that returned two thirds of its fields is
    less damaging than one that returned none, and the shrink says so."""
    probs = [_evidence_case(wired, r).decision.p_win for r in (0.0, 0.35, 1.0)]
    assert probs[0] > probs[1] > probs[2], probs
    assert all(p > 0.5 for p in probs), "shrink overshot the base rate"
    assert probs[0] - probs[1] < probs[0] - probs[2], "shrink is not proportional"
