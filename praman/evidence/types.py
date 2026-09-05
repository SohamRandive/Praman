"""Types for the evidence engine.

The engine is deterministic end to end: no model participates in deciding
whether a package is sufficient. If a required document is absent that is a fact
about record-keeping, not a probability, and nothing here is permitted to
average it away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["blocking", "warn"]
ConstraintStatus = Literal["passed", "violated", "unevaluated", "not_applicable"]
Routing = Literal["assemble", "blocked", "route_to_human"]
GapKind = Literal[
    "missing_required_field",
    "blocking_constraint",
    "non_qualifying_artifact",
    "unresolved_code",
]


@dataclass(frozen=True)
class EvidenceArtifact:
    """One retrieved document, bound to the contest() field it can satisfy.

    `api_field` is either a bare evidence field ("shipping_proof") or an
    `others[]` entry addressed by type ("others.product_description").
    `fields` carries the structured extraction; every value in it is
    individually citable by the drafter, which is what makes grounding
    checkable rather than aspirational.
    """

    artifact_id: str
    source_system: str
    artifact_type: str
    api_field: str
    content_hash: str
    retrieved_at: str
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def is_other(self) -> bool:
        return self.api_field.startswith("others.")

    @property
    def others_type(self) -> str | None:
        return self.api_field.split(".", 1)[1] if self.is_other else None


@dataclass(frozen=True)
class CaseContext:
    """Facts the constraints resolve against, outside the artifacts themselves."""

    dispute: dict[str, Any] = field(default_factory=dict)
    payment: dict[str, Any] = field(default_factory=dict)
    order: dict[str, Any] = field(default_factory=dict)
    merchant: dict[str, Any] = field(default_factory=dict)

    def lookup(self, root: str, key: str) -> tuple[bool, Any]:
        """Return (found, value). `found` is False for a genuinely absent key,
        which is what drives `unevaluated` rather than a silent pass."""
        table = getattr(self, root, None)
        if not isinstance(table, dict) or key not in table:
            return False, None
        return True, table[key]


@dataclass(frozen=True)
class Classification:
    """Supplied by the caller for classify_then_delegate codes.

    The engine never classifies. It accepts a classification and gates it on
    confidence, so the model stays outside the deterministic core.
    """

    code: str
    confidence: float
    rationale: str = ""


@dataclass(frozen=True)
class ArtifactRejection:
    """An artifact that could have bound to a field but was disqualified.

    Recorded rather than dropped: a WhatsApp thread on RZP06 must be visibly
    non-qualifying, never silently uncounted.
    """

    artifact_id: str
    api_field: str
    constraint_id: str
    reason: str      # the technical detail: which value failed the predicate
    remedy: str = ""  # what the merchant should actually do about it


@dataclass(frozen=True)
class ConstraintOutcome:
    constraint_id: str
    kind: str
    severity: Severity
    status: ConstraintStatus
    message: str = ""
    remedy: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Gap:
    """A named, actionable gap. Never a bare boolean.

    "No signed delivery confirmation - request from courier, or accept" is
    something a merchant can act on. `required_coverage: 0.75` is not.
    """

    kind: GapKind
    name: str
    remedy: str
    api_field: str | None = None
    constraint_id: str | None = None


@dataclass(frozen=True)
class ResolvedRequirements:
    """A reason code resolved to concrete requirements for this specific case."""

    reason_code: str
    resolved_code: str
    network: str
    title: str
    required: tuple[str, ...]
    supporting: tuple[str, ...]
    constraints: tuple[dict[str, Any], ...]
    resolution_note: str = ""
    routing: Routing = "assemble"
    unresolved_reason: str = ""


@dataclass
class EvidencePackage:
    """Shaped so `api_payload` is the contest() request body verbatim."""

    reason_code: str
    resolved_code: str
    network: str
    required: list[str]
    supporting: list[str]
    bound: dict[str, list[str]]
    rejected: list[ArtifactRejection]
    constraint_outcomes: list[ConstraintOutcome]
    blocking_gaps: list[Gap]
    warnings: list[Gap]
    completeness_score: float
    required_coverage: float
    sufficient: bool
    routing: Routing
    api_payload: dict[str, Any]

    @property
    def unevaluated_constraints(self) -> list[str]:
        return [c.constraint_id for c in self.constraint_outcomes if c.status == "unevaluated"]

    @property
    def violated_constraints(self) -> list[str]:
        """Blocking violations only.

        A warn-severity rule that fails is reported in `warnings`, not here.
        Returning both made a late delivery look like a disqualifying defect in
        the same list as a delivery that post-dated the dispute, and would have
        fed a feature that conflated "shapes the narrative" with "loses the
        case".
        """
        return [
            c.constraint_id
            for c in self.constraint_outcomes
            if c.status == "violated" and c.severity == "blocking"
        ]

    @property
    def warned_constraints(self) -> list[str]:
        return [
            c.constraint_id
            for c in self.constraint_outcomes
            if c.status == "violated" and c.severity == "warn"
        ]
