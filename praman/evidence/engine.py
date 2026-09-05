"""Evidence assembly: bind artifacts to fields, score, block, emit.

The rule that makes this a tool rather than a liability is step 4: if any
required field is unbound, the package is blocked and a *named* gap is emitted.
The drafter is never handed a hole to paper over with prose.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .constraints import (
    evaluate_cross_field,
    evaluate_package_wide,
    qualifies,
    rejection,
)
from .types import (
    ArtifactRejection,
    CaseContext,
    ConstraintOutcome,
    EvidenceArtifact,
    EvidencePackage,
    Gap,
    ResolvedRequirements,
)

# Human labels for gaps. "No signed delivery confirmation - request it from the
# courier, or accept" is something a merchant can act on this afternoon.
# "required_coverage: 0.75" is not.
FIELD_LABELS: dict[str, str] = {
    "shipping_proof": "proof of delivery",
    "billing_proof": "billing or transaction record",
    "cancellation_proof": "cancellation record",
    "customer_communication": "correspondence with the cardholder",
    "proof_of_service": "proof the service was rendered",
    "explanation_letter": "explanation letter",
    "refund_confirmation": "refund confirmation",
    "access_activity_log": "account access or usage log",
    "refund_cancellation_policy": "published refund and cancellation policy",
    "term_and_conditions": "published terms and conditions",
}

FIELD_REMEDIES: dict[str, str] = {
    "shipping_proof": "Request the signed proof of delivery from the courier, or accept.",
    "customer_communication": "Attach the support thread with the cardholder, or accept.",
    "refund_confirmation": "Attach the refund confirmation for this payment, or accept.",
    "access_activity_log": "Export the account access log covering the billing period.",
    "refund_cancellation_policy": "Attach the policy version in force on the transaction date.",
    "term_and_conditions": "Attach the terms in force on the transaction date.",
    "billing_proof": "Attach the payment or settlement record for this transaction.",
    "proof_of_service": "Attach evidence the service was rendered.",
}


def label_for(api_field: str) -> str:
    if api_field in FIELD_LABELS:
        return FIELD_LABELS[api_field]
    if api_field.startswith("others."):
        return api_field.split(".", 1)[1].replace("_", " ")
    return api_field.replace("_", " ")


def remedy_for(api_field: str) -> str:
    return FIELD_REMEDIES.get(
        api_field, f"Obtain the {label_for(api_field)} and attach it, or accept."
    )


def _bind(
    artifacts: Iterable[EvidenceArtifact],
    requirements: ResolvedRequirements,
    context: CaseContext,
) -> tuple[dict[str, list[EvidenceArtifact]], list[ArtifactRejection]]:
    """Bind artifacts to fields, enforcing this code's field qualifiers.

    A disqualified artifact is *rejected with a reason*, never dropped. That is
    the whole point of RZP06: a WhatsApp thread must be visibly non-qualifying,
    because silently uncounting it is how a merchant loses a dispute while
    believing the package was complete.
    """
    qualifiers: dict[str, list[dict[str, Any]]] = {}
    for con in requirements.constraints:
        if con.get("kind") == "field_qualifier":
            qualifiers.setdefault(con["field"], []).append(con)

    bound: dict[str, list[EvidenceArtifact]] = {}
    rejected: list[ArtifactRejection] = []

    for art in artifacts:
        blocked = False
        for con in qualifiers.get(art.api_field, []):
            ok, detail = qualifies(con, art, context)
            if not ok:
                rejected.append(rejection(con, art, detail))
                blocked = True
                break
        if not blocked:
            bound.setdefault(art.api_field, []).append(art)

    return bound, rejected


def _score(
    bound: dict[str, list[EvidenceArtifact]],
    requirements: ResolvedRequirements,
    scoring: dict[str, Any],
) -> tuple[float, float, list[str]]:
    req_w = float(scoring.get("required_weight", 1.0))
    sup_w = float(scoring.get("supporting_weight", 0.3))

    missing_required = [f for f in requirements.required if not bound.get(f)]
    covered_required = len(requirements.required) - len(missing_required)
    covered_supporting = sum(1 for f in requirements.supporting if bound.get(f))

    total = req_w * len(requirements.required) + sup_w * len(requirements.supporting)
    earned = req_w * covered_required + sup_w * covered_supporting
    completeness = round(earned / total, 6) if total else 1.0

    coverage = (
        round(covered_required / len(requirements.required), 6)
        if requirements.required
        else 1.0
    )
    return completeness, coverage, missing_required


def _evaluate_constraints(
    requirements: ResolvedRequirements,
    bound: dict[str, list[EvidenceArtifact]],
    context: CaseContext,
    absent_required: frozenset[str],
) -> list[ConstraintOutcome]:
    outcomes: list[ConstraintOutcome] = []
    for con in requirements.constraints:
        kind = con.get("kind", "cross_field")
        if kind == "field_qualifier":
            continue  # already applied at bind time
        if kind == "package_wide":
            outcomes.append(evaluate_package_wide(con, bound, absent_required))
        else:
            outcomes.append(evaluate_cross_field(con, context, bound, absent_required))
    return outcomes


def _api_payload(
    bound: dict[str, list[EvidenceArtifact]],
    context: CaseContext,
    summary: str,
) -> dict[str, Any]:
    """The contest() request body, verbatim.

    `action` is hard-coded to "draft". There is no code path in this repository
    that sets it to "submit"; a human approval does that, and writes its own
    audit record when it does.
    """
    payload: dict[str, Any] = {}
    amount = context.dispute.get("amount_minor")
    if amount is not None:
        payload["amount"] = amount

    others: list[dict[str, Any]] = []
    for api_field, arts in sorted(bound.items()):
        doc_ids = [a.artifact_id for a in arts]
        if api_field.startswith("others."):
            others.append({"type": api_field.split(".", 1)[1], "document_ids": doc_ids})
        else:
            payload[api_field] = doc_ids
    if others:
        payload["others"] = others

    payload["summary"] = summary
    payload["action"] = "draft"
    return payload


def assemble(
    requirements: ResolvedRequirements,
    artifacts: Iterable[EvidenceArtifact],
    context: CaseContext | None = None,
    scoring: dict[str, Any] | None = None,
    summary: str = "",
) -> EvidencePackage:
    context = context or CaseContext()
    scoring = scoring or {"required_weight": 1.0, "supporting_weight": 0.3}
    artifacts = list(artifacts)

    bound, rejected = _bind(artifacts, requirements, context)
    completeness, coverage, missing_required = _score(bound, requirements, scoring)
    outcomes = _evaluate_constraints(
        requirements, bound, context, frozenset(missing_required)
    )

    blocking_gaps: list[Gap] = []
    warnings: list[Gap] = []

    # The reason code itself could not be resolved to concrete requirements.
    if requirements.routing == "route_to_human":
        blocking_gaps.append(
            Gap(
                kind="unresolved_code",
                name=f"Reason code {requirements.reason_code} could not be resolved.",
                remedy=requirements.unresolved_reason,
            )
        )

    rejected_by_field: dict[str, list[ArtifactRejection]] = {}
    for rej in rejected:
        rejected_by_field.setdefault(rej.api_field, []).append(rej)

    for fld in missing_required:
        rejects = rejected_by_field.get(fld)
        if rejects:
            # The document exists but does not qualify - say so, precisely.
            # The remedy a merchant reads must be an instruction, not the
            # predicate detail that produced it. "artifact.channel='whatsapp'"
            # is true and useless; "supply the email thread, or accept" is
            # something they can act on this afternoon.
            blocking_gaps.append(
                Gap(
                    kind="non_qualifying_artifact",
                    name=(
                        f"The {label_for(fld)} on file does not qualify for "
                        f"{requirements.resolved_code} ({rejects[0].constraint_id})."
                    ),
                    remedy=rejects[0].remedy or remedy_for(fld),
                    api_field=fld,
                    constraint_id=rejects[0].constraint_id,
                )
            )
        else:
            blocking_gaps.append(
                Gap(
                    kind="missing_required_field",
                    name=f"No {label_for(fld)}.",
                    remedy=remedy_for(fld),
                    api_field=fld,
                )
            )

    unverifiable = False
    for out in outcomes:
        if out.severity == "warn":
            if out.status == "violated":
                warnings.append(
                    Gap(
                        kind="blocking_constraint",
                        name=out.message or out.constraint_id,
                        remedy=out.remedy,
                        constraint_id=out.constraint_id,
                    )
                )
            continue
        if out.status == "violated":
            blocking_gaps.append(
                Gap(
                    kind="blocking_constraint",
                    name=out.message or out.constraint_id,
                    remedy=out.remedy,
                    constraint_id=out.constraint_id,
                )
            )
        elif out.status == "unevaluated":
            # ADR-008: declared, never assumed passed.
            unverifiable = True
            blocking_gaps.append(
                Gap(
                    kind="blocking_constraint",
                    name=f"Cannot verify {out.constraint_id}: {out.detail}.",
                    remedy=out.remedy or "Supply the missing fact, or route to a human.",
                    constraint_id=out.constraint_id,
                )
            )

    sufficient = not blocking_gaps and coverage >= 1.0

    if sufficient:
        routing = "assemble"
    elif requirements.routing == "route_to_human" or unverifiable:
        routing = "route_to_human"
    else:
        routing = "blocked"

    return EvidencePackage(
        reason_code=requirements.reason_code,
        resolved_code=requirements.resolved_code,
        network=requirements.network,
        required=list(requirements.required),
        supporting=list(requirements.supporting),
        bound={k: [a.artifact_id for a in v] for k, v in sorted(bound.items())},
        rejected=rejected,
        constraint_outcomes=outcomes,
        blocking_gaps=blocking_gaps,
        warnings=warnings,
        completeness_score=completeness,
        required_coverage=coverage,
        sufficient=sufficient,
        routing=routing,  # type: ignore[arg-type]
        api_payload=_api_payload(bound, context, summary),
    )
