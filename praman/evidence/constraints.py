"""Deterministic constraint evaluation.

Predicates are structured data, never eval'd strings. A constraint whose
operands cannot be resolved is reported `unevaluated`, never passed - see
ADR-008. A corpus or a package that quietly assumes unmodelled constraints hold
would inflate winnability, and the inflation would be invisible downstream.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import (
    ArtifactRejection,
    CaseContext,
    ConstraintOutcome,
    EvidenceArtifact,
)

CONTEXT_ROOTS = ("dispute", "payment", "order", "merchant")
ARTIFACT_ROOT = "artifact"

class _Missing:
    """Single sentinel for an operand that could not be resolved.

    Public and shared: a module that defines its own copy will silently fail
    every `is MISSING` identity check against this one.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<MISSING>"


MISSING = _Missing()


class ConstraintError(ValueError):
    """Raised at load time for a malformed constraint. Never at evaluation time."""


# --------------------------------------------------------------------- values


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 8 or not text[0].isdigit():
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_pair(left: Any, right: Any) -> tuple[Any, Any]:
    """Make two operands comparable, or leave them alone.

    Timestamps arrive as ISO strings and must compare as instants, not as text:
    a naive string compare silently does the right thing until a timezone offset
    appears, then silently does the wrong one.
    """
    ldt, rdt = _parse_dt(left), _parse_dt(right)
    if ldt is not None and rdt is not None:
        if (ldt.tzinfo is None) != (rdt.tzinfo is None):
            raise _Incomparable("mixed naive and aware timestamps")
        return ldt, rdt
    if isinstance(left, bool) or isinstance(right, bool):
        return left, right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left, right
    return left, right


class _Incomparable(Exception):
    pass


# ------------------------------------------------------------------- operands


def resolve_operand(
    path: Any,
    context: CaseContext,
    bound: dict[str, list[EvidenceArtifact]],
    artifact: EvidenceArtifact | None = None,
) -> tuple[Any, str]:
    """Resolve one operand.

    Returns (value, detail). A value of `MISSING` means the operand could not be
    resolved and the constraint is therefore unevaluated. Non-string operands are
    literals and always resolve to themselves.
    """
    if not isinstance(path, str) or "." not in path:
        return path, f"literal {path!r}"

    root, key = path.split(".", 1)

    if root in CONTEXT_ROOTS:
        found, value = context.lookup(root, key)
        if not found:
            return MISSING, f"{path} absent from case context"
        if value is None:
            return MISSING, f"{path} is null"
        return value, f"{path}={value!r}"

    if root == ARTIFACT_ROOT:
        if artifact is None:
            return MISSING, f"{path} has no artifact in scope"
        if key not in artifact.fields:
            return MISSING, f"{path} absent on {artifact.artifact_id}"
        return artifact.fields[key], f"{path}={artifact.fields[key]!r}"

    # Otherwise an evidence field: read the key off the artifacts bound to it.
    artifacts = bound.get(root) or []
    if not artifacts:
        return MISSING, f"no artifact bound to {root}"
    for art in artifacts:
        if key in art.fields and art.fields[key] is not None:
            return art.fields[key], f"{path}={art.fields[key]!r} ({art.artifact_id})"
    return MISSING, f"{key} absent on every artifact bound to {root}"


# ---------------------------------------------------------------- comparison


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "is_true":
        return left is True
    if op == "in":
        return left in right
    if op == "not_in":
        return left not in right
    if op == "eq":
        return bool(left == right)
    if op == "ne":
        return bool(left != right)

    left, right = _coerce_pair(left, right)
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    raise ConstraintError(f"unknown predicate op {op!r}")


VALID_OPS = frozenset(
    {"lt", "lte", "gt", "gte", "eq", "ne", "in", "not_in", "is_true", "all_gt"}
)


def validate_predicate(pred: dict[str, Any], where: str) -> None:
    op = pred.get("op")
    if op not in VALID_OPS:
        raise ConstraintError(f"{where}: unknown op {op!r}")
    if "left" not in pred:
        raise ConstraintError(f"{where}: predicate has no left operand")
    if op not in ("is_true",) and "right" not in pred:
        raise ConstraintError(f"{where}: op {op!r} needs a right operand")


# ----------------------------------------------------------------- evaluation


def _outcome(
    spec: dict[str, Any], status: str, detail: str
) -> ConstraintOutcome:
    return ConstraintOutcome(
        constraint_id=spec["id"],
        kind=spec.get("kind", "cross_field"),
        severity=spec.get("severity", "blocking"),
        status=status,  # type: ignore[arg-type]
        message=spec.get("message", "").strip(),
        remedy=spec.get("remedy", "").strip(),
        detail=detail,
    )


def referenced_fields(pred: dict[str, Any]) -> set[str]:
    """Evidence-field roots a predicate reads, e.g. {"shipping_proof"}."""
    roots = set()
    for operand in (pred.get("left"), pred.get("right")):
        if isinstance(operand, str) and "." in operand:
            root = operand.split(".", 1)[0]
            if root not in CONTEXT_ROOTS and root != ARTIFACT_ROOT:
                roots.add(root)
    return roots


def evaluate_cross_field(
    spec: dict[str, Any],
    context: CaseContext,
    bound: dict[str, list[EvidenceArtifact]],
    absent_required: frozenset[str] = frozenset(),
) -> ConstraintOutcome:
    pred = spec["predicate"]
    op = pred["op"]

    # A constraint that governs a document already reported missing is not a
    # second, independent failure. Reporting it as "cannot verify" would count
    # one absent delivery record as both a gap and an unverifiable constraint,
    # inflating the exception list with noise a merchant cannot act on twice.
    already_gapped = referenced_fields(pred) & absent_required
    if already_gapped:
        return _outcome(
            spec,
            "not_applicable",
            f"governs {', '.join(sorted(already_gapped))}, already reported missing",
        )

    left, ldetail = resolve_operand(pred["left"], context, bound)
    if left is MISSING:
        return _outcome(spec, "unevaluated", ldetail)

    if op == "is_true":
        passed = _compare(op, left, None)
        return _outcome(spec, "passed" if passed else "violated", ldetail)

    right, rdetail = resolve_operand(pred["right"], context, bound)
    if right is MISSING:
        return _outcome(spec, "unevaluated", rdetail)

    try:
        passed = _compare(op, left, right)
    except (_Incomparable, TypeError) as exc:
        return _outcome(spec, "unevaluated", f"{ldetail} vs {rdetail}: {exc}")

    return _outcome(spec, "passed" if passed else "violated", f"{ldetail} vs {rdetail}")


def evaluate_package_wide(
    spec: dict[str, Any],
    bound: dict[str, list[EvidenceArtifact]],
    absent_required: frozenset[str] = frozenset(),
) -> ConstraintOutcome:
    """Applied to every bound artifact, e.g. the RuPay 1101 legibility gate."""
    pred = spec["predicate"]
    if pred["op"] != "all_gt":
        raise ConstraintError(f"{spec['id']}: package_wide supports only all_gt")

    key = pred["left"].split(".", 1)[1]
    threshold = pred["right"]

    artifacts = [a for arts in bound.values() for a in arts]
    if not artifacts:
        status = "not_applicable" if absent_required else "unevaluated"
        return _outcome(spec, status, "no artifacts bound")

    unknown, failing = [], []
    for art in artifacts:
        value = art.fields.get(key)
        if value is None:
            unknown.append(art.artifact_id)
        elif not value > threshold:
            failing.append(f"{art.artifact_id}={value}")

    if failing:
        return _outcome(spec, "violated", f"below {threshold}: {', '.join(sorted(failing))}")
    if unknown:
        return _outcome(spec, "unevaluated", f"{key} absent on: {', '.join(sorted(unknown))}")
    return _outcome(spec, "passed", f"all {len(artifacts)} artifacts above {threshold}")


def qualifies(
    spec: dict[str, Any], artifact: EvidenceArtifact, context: CaseContext
) -> tuple[bool, str]:
    """Field qualifier: may this artifact bind to this field for this code?

    A failing artifact is rejected with a recorded reason rather than dropped,
    so it can never be silently counted toward completeness.
    """
    pred = spec["predicate"]
    left, ldetail = resolve_operand(pred["left"], context, {}, artifact=artifact)
    if left is MISSING:
        return False, f"{ldetail} - cannot confirm the artifact qualifies"

    if pred["op"] == "is_true":
        return _compare("is_true", left, None), ldetail

    right, _ = resolve_operand(pred["right"], context, {}, artifact=artifact)
    try:
        return _compare(pred["op"], left, right), ldetail
    except (_Incomparable, TypeError) as exc:
        return False, f"{ldetail}: {exc}"


def rejection(
    spec: dict[str, Any], artifact: EvidenceArtifact, reason: str
) -> ArtifactRejection:
    return ArtifactRejection(
        artifact_id=artifact.artifact_id,
        api_field=artifact.api_field,
        constraint_id=spec["id"],
        reason=reason,
        remedy=spec.get("remedy", "").strip(),
    )
