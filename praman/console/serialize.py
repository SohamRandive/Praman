"""Render a decided CaseFile into the shape the console consumes.

The content model is `make trace`: the same five stages, rendered. Resolve,
bind, score, constrain, assemble - plus the deadline that forces the whole
thing. No new information architecture is invented here, because the trace is
already the argument and the screen's job is to make it readable under time
pressure.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from praman.evidence.engine import label_for
from praman.orchestrator import CaseFile


def rupees(minor: int) -> str:
    """Indian digit grouping. Amounts are never abbreviated in a decision
    context - "18.4k" is not a number a merchant can reconcile."""
    sign = "-" if minor < 0 else ""
    n = str(int(round(abs(minor) / 100)))
    if len(n) <= 3:
        return f"{sign}₹{n}"
    head, tail = n[:-3], n[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"{sign}₹{','.join(parts)},{tail}"


def observation_time(dispute_id: str, created_at: str, respond_by: str) -> str:
    """A simulated present, so the queue does not read as twelve fresh cases.

    Every fixture would otherwise show its full filing window untouched, which
    makes the countdown meaningless and the depleting arc always full. The
    fraction is derived from the dispute id, so it is stable across runs and the
    same case is always at the same point in its window.

    This is a DEMO CLOCK and the console labels it as one. Nothing in the
    decision path reads it.
    """
    seed = int.from_bytes(
        hashlib.blake2b(dispute_id.encode(), digest_size=4).digest(), "big"
    )
    fraction = 0.04 + (seed % 1000) / 1000 * 0.92
    start = datetime.fromisoformat(created_at)
    window = datetime.fromisoformat(respond_by) - start
    return (start + window * fraction).isoformat()


def countdown(respond_by: str, now: str, created_at: str | None = None) -> dict[str, Any]:
    """The hero. `respond_by` is the most characteristic object in this world
    and the only thing that actually forces action.

    `elapsed` drives a depleting arc scaled to *this reason code's real filing
    window*, so a 7-day window half gone reads differently from a 21-day window
    half gone. Time is the hero of this product and it should be felt before it
    is read.
    """
    end = datetime.fromisoformat(respond_by)
    start = datetime.fromisoformat(created_at or now)
    hours = (end - datetime.fromisoformat(now)).total_seconds() / 3600
    window = max((end - start).total_seconds() / 3600, 1e-6)
    days, rem = divmod(max(hours, 0), 24)
    return {
        "days": int(days),
        "hours": int(rem),
        "total_hours": round(hours, 2),
        "window_hours": round(window, 2),
        "elapsed": round(min(max(1 - hours / window, 0.0), 1.0), 4),
        "expired": hours <= 0,
        "critical": 0 < hours <= 24,
        "at_risk": 24 < hours <= 72,
        "display": f"{int(days)}d {int(rem):02d}h" if hours > 0 else "expired",
    }


def serialize(case: CaseFile, matrix: Any) -> dict[str, Any]:
    now = observation_time(case.dispute_id, case.created_at, case.respond_by)
    evidence = case.agent_results.get("evidence")
    payload = evidence.payload if evidence and evidence.usable else {}
    reqs = payload.get("requirements")
    decision = case.decision
    spec = matrix.codes.get(case.reason_code, {})

    present = set(payload.get("fields_present", ()))
    unavailable = set(payload.get("unavailable", ()))
    artifacts = payload.get("artifacts") or {}

    def field_row(field: str, required: bool) -> dict[str, Any]:
        return {
            "field": field,
            "label": label_for(field),
            "required": required,
            "present": field in present,
            # Distinguishes "the merchant never kept it" from "the source did
            # not answer just now" - different problems, different remedies.
            "unavailable": field in unavailable,
        }

    checklist = [field_row(f, True) for f in (reqs.required if reqs else ())]
    checklist += [field_row(f, False) for f in (reqs.supporting if reqs else ())]

    component = case.payload("network", "component") or {}
    comparable = case.payload("precedent", "comparable")

    # Constraint outcomes, keyed by rule id. `blocking` disqualifies the
    # package, `warn` shapes the narrative, `unevaluated` is declared unknown.
    outcomes: dict[str, str] = {}
    for cid in case.raw.get("violated_constraints", ()):
        outcomes[cid] = "violated"
    for cid in case.raw.get("warnings", ()):
        outcomes[cid] = "warned"
    for cid in case.raw.get("unevaluated_constraints", ()):
        outcomes[cid.split(":", 1)[-1]] = "unevaluated"

    # Below the cost of contesting is a distinct state, not a low probability.
    # No evidence and no model can make a Rs 200 dispute worth Rs 350 to fight.
    cost_minor = decision.cost_minor if decision else 35_000
    below_cost = case.amount_minor <= cost_minor

    return {
        "case_id": case.case_id,
        "dispute_id": case.dispute_id,
        "merchant_id": case.merchant_id,
        "reason_code": case.reason_code,
        "resolved_code": reqs.resolved_code if reqs else case.reason_code,
        "title": spec.get("title", ""),
        "network": spec.get("network", ""),
        "phase": case.raw.get("phase", ""),
        "amount_minor": case.amount_minor,
        "amount": rupees(case.amount_minor),
        "contest_cost": rupees(cost_minor),
        "below_cost": below_cost,
        "created_at": case.created_at,
        "respond_by": case.respond_by,
        "observed_at": now,
        "deadline": countdown(case.respond_by, now, case.created_at),

        "evidence": {
            "checklist": checklist,
            "required_total": len(reqs.required) if reqs else 0,
            "required_met": sum(1 for r in checklist if r["required"] and r["present"]),
            "completeness": payload.get("completeness", 0.0),
            "required_coverage": payload.get("required_coverage", 0.0),
            "sufficient": bool(payload.get("sufficient", False)),
            "routing": payload.get("routing", "blocked"),
            "gaps": [
                {"name": g, "remedy": ""} if isinstance(g, str) else g
                for g in payload.get("blocking_gaps", ())
            ],
            "resolution_note": reqs.resolution_note if reqs else "",
        },

        # Stage 4 of the trace. Each rule carries the outcome AND whether it is
        # published or ours, because the required/supporting split is our
        # judgement and a screen that hides that reads as documentation.
        "constraints": [
            {
                "id": c["id"],
                "severity": c["severity"],
                "source": c.get("source", "inferred"),
                "message": (c.get("message") or "").strip(),
                "remedy": (c.get("remedy") or "").strip(),
                "status": outcomes.get(c["id"], "not_applicable"),
            }
            for c in (reqs.constraints if reqs else ())
        ],
        "rejections": [
            {
                "field": r["api_field"],
                "label": label_for(r["api_field"]),
                "constraint_id": r["constraint_id"],
            }
            for r in case.raw.get("rejected_artifacts", ())
        ],

        "recommendation": None if decision is None else {
            "action": decision.action,
            "p_win": decision.p_win,
            "break_even": decision.break_even_p,
            "expected_value": rupees(decision.expected_value_minor),
            "expected_value_minor": decision.expected_value_minor,
            "cost": rupees(decision.cost_minor),
            "rationale": decision.rationale,
            "overrides": list(decision.overrides),
            "comparable": list(comparable) if comparable else None,
        },

        "network_finding": {
            "component_size": int(component.get("component_size", 1)),
            "prior_disputes": int(component.get("component_prior_disputes", 0)),
            "prior_merchants": int(component.get("component_prior_merchants", 0)),
            "disputes_per_day": round(component.get("component_disputes_per_day", 0.0), 2),
            "shares_entity": bool(component.get("component_shares_entity", 0)),
        },

        "agents": [
            {
                "name": r.agent,
                "status": r.status,
                "confidence": r.confidence,
                "errors": list(r.errors),
            }
            for r in sorted(case.agent_results.values(), key=lambda r: r.agent)
        ],

        # The drafted narrative, with every claim's citations attached so the
        # grounding is legible rather than asserted. `None` where drafting does
        # not apply - an accepted dispute has no filing to write.
        "draft": None if case.draft is None else {
            "summary": case.draft.summary,
            "blocked": case.draft.blocked,
            "block_reason": case.draft.block_reason,
            "provider": case.draft.provider,
            "truncated": case.draft.truncated,
            "coverage_before": case.draft.coverage_before,
            "coverage_after": case.draft.coverage_after,
            "groundedness": case.draft.groundedness,
            "claims": [
                {
                    "id": c.claim_id,
                    "text": c.text,
                    "required": c.required,
                    "field": c.api_field,
                    "label": label_for(c.api_field) if c.api_field else "",
                    # Field-level, so a reader can check the sentence against the
                    # document rather than trusting that someone did.
                    "citations": [
                        {"ref": cit.ref, "artifact": cit.artifact_id,
                         "field": cit.field_name,
                         "value": str(artifacts[cit.artifact_id].fields[cit.field_name])
                         if cit.artifact_id in artifacts
                         and cit.field_name in artifacts[cit.artifact_id].fields else ""}
                        for cit in c.citations
                    ],
                }
                for c in case.draft.claims
            ],
            # Every strip is shown. A verifier whose catches are hidden is a
            # verifier the reader has to take on trust.
            "stripped": [
                {"text": s.text, "reason": s.reason, "detail": s.detail}
                for s in case.draft.stripped
            ],
        },

        # Full record bodies, so the console can RECOMPUTE the chain in the
        # browser rather than being told it is intact. A claim of tamper-evidence
        # that the reader has to take on trust is not evidence of anything.
        "audit": [
            {
                "ts": r.ts,
                "actor": r.actor,
                "event": r.event,
                "inputs_hash": r.inputs_hash,
                "outputs_hash": r.outputs_hash,
                "prev_hash": r.prev_hash,
                "record_hash": r.record_hash,
            }
            for r in case.audit.records
        ],
        "audit_intact": not case.audit.verify(),
    }
