"""Drafting and grounding.

The one place a language model writes anything, and the deterministic verifier
that decides whether what it wrote is allowed to leave the building.
"""

from .artifacts import synthesize
from .draft import (
    COVERAGE_FLOOR,
    SUMMARY_LIMIT,
    assemble_summary,
    contest_payload,
    draft_representment,
)
from .provider import FaultInjectingProvider, LLMProvider, TemplatedProvider
from .types import Citation, Claim, DraftResult, Strip
from .verifier import checkable_values, coverage, verify, verify_claim

__all__ = [
    "COVERAGE_FLOOR",
    "SUMMARY_LIMIT",
    "Citation",
    "Claim",
    "DraftResult",
    "FaultInjectingProvider",
    "LLMProvider",
    "Strip",
    "TemplatedProvider",
    "assemble_summary",
    "checkable_values",
    "contest_payload",
    "coverage",
    "draft_representment",
    "synthesize",
    "verify",
    "verify_claim",
]
