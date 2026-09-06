"""Fan-out, partial-failure merge, and the decision.

Partial-failure tolerance is **the default path, not an error path**. The
orchestrator does not distinguish "all agents answered" from "three answered";
it merges whatever came back, records what did not, and decides. Degradation
widens the confidence band and is reported in the output rather than absorbed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from praman.adjudicator import decide
from praman.orchestrator.case import CaseFile
from praman.orchestrator.contract import Agent, deadline_budget, guarded

# A decision built on fewer sources is not more uncertain in the model's eyes -
# it is more uncertain in ours. Shrinking p toward the base rate is the honest
# way to say so, and it is deterministic.
DEGRADATION_SHRINK = 0.12


async def dispatch(case: CaseFile, agents: list[Agent]) -> dict[str, Any]:
    """Run every agent concurrently under its own budget.

    Per-agent timeouts, not one global timeout: a slow graph query must not
    starve evidence retrieval, which is the one agent whose absence blocks a
    package outright.
    """
    hours = (
        datetime.fromisoformat(case.respond_by) - datetime.fromisoformat(case.created_at)
    ).total_seconds() / 3600
    budgets = deadline_budget(hours, [a.name for a in agents])

    case.audit.append("system", "agents.dispatched",
                      {"case_id": case.case_id}, {"budgets": budgets})

    results = await asyncio.gather(
        *(guarded(a, case, budgets[a.name]) for a in agents)
    )
    for r in results:
        case.agent_results[r.agent] = r
        case.audit.append(f"agent:{r.agent}", "agent.returned",
                          {"budget_ms": budgets[r.agent]},
                          {"status": r.status, "errors": list(r.errors)})
    return budgets


def adjudicate(case: CaseFile, p_win: float, cost_minor: int) -> Any:
    """Contest or accept. A deterministic inequality, with degradation priced in."""
    evidence = case.agent_results.get("evidence")
    have_evidence = evidence is not None and evidence.usable
    sufficient = bool(case.payload("evidence", "sufficient", False))
    gaps = tuple(case.payload("evidence", "blocking_gaps", ()) or ())

    # Evidence retrieval is the one agent whose loss is not survivable as a
    # *contest*: without it we cannot know whether a package can be assembled,
    # and filing blind spends the contest cost to lose the same money. Every
    # other agent can fail and the case still decides.
    if not have_evidence:
        sufficient = False
        gaps = ("Evidence could not be retrieved, so the package cannot be verified.",)

    # A decision built on fewer sources is more uncertain, and how much more
    # depends on how much was lost. A wholly absent agent shrinks by the full
    # step; one that returned two thirds of its fields shrinks by a third of it.
    shrunk = p_win
    for _ in case.missing:
        shrunk += (0.5 - shrunk) * DEGRADATION_SHRINK
    for result in sorted(case.agent_results.values(), key=lambda r: r.agent):
        if result.status == "degraded":
            lost = 1.0 - max(0.0, min(1.0, result.confidence))
            shrunk += (0.5 - shrunk) * DEGRADATION_SHRINK * lost

    comparable = case.payload("precedent", "comparable")
    component = case.payload("network", "component") or {}
    ring = ""
    if component.get("component_size", 0) > 1:
        ring = (f"identity shares entities with {int(component['component_size']) - 1} "
                f"others across {int(component.get('component_prior_merchants', 0))} merchants.")

    decision = decide(
        shrunk, case.amount_minor, cost_minor,
        evidence_sufficient=sufficient,
        blocking_gaps=gaps,
        comparable=comparable,
        ring=ring,
    )
    case.decision = decision
    case.package = evidence.payload if have_evidence else None
    case.audit.append("system", "decision.made",
                      {"p_win": p_win, "shrunk": shrunk, "missing": case.missing},
                      {"action": decision.action, "ev": decision.expected_value_minor})
    return decision


def draft_if_contesting(case: CaseFile, provider: Any = None) -> Any:
    """Draft the representment, but only on the contest path.

    Nothing is drafted for an accepted dispute: there is no filing to write, and
    generating prose nobody will submit would be the model doing work purely to
    look busy. Drafting also runs *after* the decision, never before it, so the
    prose cannot influence what was already decided by an inequality.

    Returns the `DraftResult`, or None where drafting does not apply.
    """
    from praman.drafting import draft_representment

    decision = case.decision
    if decision is None or decision.action != "contest":
        return None

    evidence = case.agent_results.get("evidence")
    if evidence is None or not evidence.usable:
        return None
    artifacts = evidence.payload.get("artifacts") or {}
    reqs = evidence.payload.get("requirements")
    required = tuple(reqs.required) if reqs is not None else ()

    result = draft_representment(
        artifacts, required, {"dispute_id": case.dispute_id}, provider=provider)
    case.draft = result

    # Every strip is logged. A verifier whose catches are not recorded is a
    # verifier nobody can audit after the fact.
    case.audit.append(
        "system", "draft.verified",
        {"claims_in": len(result.claims) + len(result.stripped),
         "provider": result.provider},
        {"claims_out": len(result.claims),
         "stripped": [{"reason": s.reason, "detail": s.detail} for s in result.stripped],
         "coverage": result.coverage_after,
         "blocked": result.blocked},
    )
    return result


async def run_case(
    case: CaseFile, agents: list[Agent], p_win: float, cost_minor: int = 35_000,
    provider: Any = None,
) -> CaseFile:
    case.audit.append("system", "dispute.created", {"dispute_id": case.dispute_id}, None)
    await dispatch(case, agents)
    adjudicate(case, p_win, cost_minor)
    draft_if_contesting(case, provider)
    return case
