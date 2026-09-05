"""Deterministic evidence engine. No model participates in this package."""

from .constraints import MISSING, ConstraintError
from .engine import FIELD_LABELS, assemble, label_for, remedy_for
from .matrix import MatrixError, ReasonCodeMatrix
from .types import (
    ArtifactRejection,
    CaseContext,
    Classification,
    ConstraintOutcome,
    EvidenceArtifact,
    EvidencePackage,
    Gap,
    ResolvedRequirements,
)

__all__ = [
    "MISSING",
    "ArtifactRejection",
    "CaseContext",
    "Classification",
    "ConstraintError",
    "ConstraintOutcome",
    "EvidenceArtifact",
    "EvidencePackage",
    "FIELD_LABELS",
    "Gap",
    "MatrixError",
    "ReasonCodeMatrix",
    "ResolvedRequirements",
    "assemble",
    "label_for",
    "remedy_for",
]
