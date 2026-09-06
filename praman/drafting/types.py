"""Types for drafting and grounding.

The output of this module is a factual statement submitted to a bank. A
fabricated delivery date in a representment is not a bad user experience, it is
a false statement made to a financial institution on a merchant's behalf. So
every sentence is an object with citations attached, and a sentence that cannot
resolve its citations does not reach the payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StripReason = Literal[
    "no_citation",          # the sentence cited nothing at all
    "unresolved_artifact",  # cited an artifact that is not in the package
    "unresolved_field",     # cited a field the artifact does not carry
    "value_mismatch",       # asserted a value the cited field does not hold
    "unsupported_value",    # a value in the prose appears in no cited field
]


@dataclass(frozen=True)
class Citation:
    """One `artifact_id.field` pointer.

    Field-level rather than document-level on purpose: "cites the shipping
    proof" is not checkable, "cites `art_ship_7f2.delivered_at`, whose value is
    2026-03-12" is.
    """

    artifact_id: str
    field_name: str

    @property
    def ref(self) -> str:
        return f"{self.artifact_id}.{self.field_name}"

    @classmethod
    def parse(cls, ref: str) -> Citation:
        artifact_id, _, field_name = ref.partition(".")
        return cls(artifact_id, field_name)


@dataclass(frozen=True)
class Claim:
    """One sentence, with everything needed to check it.

    `asserts` maps a citation ref to the value this sentence states for it. It
    exists so the check is exact rather than a substring guess - but it is not
    trusted on its own, because a fabrication puts a wrong value in `text`
    while leaving `asserts` consistent. The verifier reads both.
    """

    claim_id: str
    text: str
    citations: tuple[Citation, ...] = ()
    asserts: dict[str, object] = field(default_factory=dict)
    api_field: str | None = None   # the evidence field this sentence speaks to
    required: bool = False

    @property
    def grounded_by_schema(self) -> bool:
        """A claim with no citations is malformed, not merely weak."""
        return bool(self.citations)


@dataclass(frozen=True)
class Strip:
    """A removed claim and the precise reason. Every strip is logged."""

    claim_id: str
    text: str
    reason: StripReason
    detail: str


@dataclass
class DraftResult:
    """What the drafting step produces, whether or not it succeeded.

    `blocked` is not an error state - it is the designed behaviour when
    stripping ungrounded sentences drops required coverage. The draft is
    blocked and escalated, never silently shortened into something that reads
    complete and is not.
    """

    summary: str
    claims: list[Claim]
    stripped: list[Strip]
    blocked: bool
    block_reason: str
    coverage_before: float
    coverage_after: float
    required_fields: tuple[str, ...]
    covered_fields: tuple[str, ...]
    truncated: bool = False
    provider: str = ""

    @property
    def groundedness(self) -> float:
        """Share of surviving claims that resolved every citation.

        By construction this is 1.0 whenever a draft is emitted: anything less
        was stripped before assembly. It is reported anyway, because a number
        that is 1.0 by construction is only meaningful if it is measured rather
        than asserted.
        """
        return 1.0 if self.claims else 0.0

    @property
    def api_action(self) -> str:
        """Hard-coded. There is no code path in this system that returns
        `submit`; a human approval does that and writes its own audit record."""
        return "draft"
