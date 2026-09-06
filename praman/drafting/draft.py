"""Draft, verify, strip, re-check coverage, then emit or block.

The order matters and is the whole design. Generation happens first and is
allowed to be wrong; verification happens second and is not. Nothing a provider
returns reaches the payload without resolving against an artifact that is
actually in the package.

`action` is hard-coded to `draft` here and nowhere sets `submit`. A human
approval does that, and writes its own audit record when it does.
"""

from __future__ import annotations

from typing import Any

from praman.evidence.engine import label_for
from praman.evidence.types import EvidenceArtifact

from .provider import LLMProvider, TemplatedProvider
from .types import Claim, DraftResult
from .verifier import coverage, verify

#: Required-field coverage below which a draft is blocked rather than emitted.
#: 1.0 is deliberate and matches the evidence engine: a package missing a
#: required document is blocked there, so a narrative missing a required
#: document is blocked here. Anything lower would let the draft quietly assert
#: less than the package promised.
COVERAGE_FLOOR = 1.0

#: The contest() API's summary limit.
SUMMARY_LIMIT = 1000


def assemble_summary(claims: list[Claim], limit: int = SUMMARY_LIMIT) -> tuple[str, bool]:
    """Required claims first, then supporting, truncated at a sentence boundary.

    Prioritised rather than merely truncated: if something has to be dropped for
    length it must be the supporting colour, never the required document the
    issuer is actually looking for.
    """
    ordered = [c for c in claims if c.required] + [c for c in claims if not c.required]
    out: list[str] = []
    used = 0
    truncated = False
    for claim in ordered:
        piece = claim.text.strip()
        addition = len(piece) + (1 if out else 0)
        if used + addition > limit:
            truncated = True
            continue
        out.append(piece)
        used += addition
    return " ".join(out), truncated


def draft_representment(
    artifacts: dict[str, EvidenceArtifact],
    required: tuple[str, ...],
    case: dict[str, Any],
    provider: LLMProvider | None = None,
    coverage_floor: float = COVERAGE_FLOOR,
) -> DraftResult:
    """The full path from package to payload-ready summary.

    Returns a `DraftResult` in every case, including the blocked one. Blocking
    is a designed outcome, not an exception: a draft that lost a required
    sentence to the verifier is escalated to a human, never shortened into
    something that reads complete.
    """
    provider = provider or TemplatedProvider()
    claims = provider.draft(artifacts, required, case)

    survivors, strips, before, after, covered = verify(claims, artifacts, required)

    if after < coverage_floor:
        missing = tuple(sorted(set(required) - set(covered)))
        reason = (
            "Grounding stripped every sentence supporting "
            + ", ".join(label_for(f) for f in missing)
            + ". The draft is blocked rather than filed without it."
        ) if missing else "Required coverage fell below the floor after grounding."
        return DraftResult(
            summary="",
            claims=survivors,
            stripped=strips,
            blocked=True,
            block_reason=reason,
            coverage_before=before,
            coverage_after=after,
            required_fields=tuple(required),
            covered_fields=covered,
            provider=getattr(provider, "name", "unknown"),
        )

    summary, truncated = assemble_summary(survivors)
    # Truncation must not silently undo the coverage guarantee it was just
    # checked against, so what actually reached the summary is re-measured.
    emitted = [c for c in survivors if c.text.strip() in summary]
    final_coverage, final_covered = coverage(emitted, required)

    return DraftResult(
        summary=summary,
        claims=emitted,
        stripped=strips,
        blocked=False,
        block_reason="",
        coverage_before=before,
        coverage_after=final_coverage,
        required_fields=tuple(required),
        covered_fields=final_covered,
        truncated=truncated,
        provider=getattr(provider, "name", "unknown"),
    )


def contest_payload(
    package_payload: dict[str, Any], draft: DraftResult, amount_minor: int
) -> dict[str, Any]:
    """The contest() request body, with `action` hard-coded to `draft`.

    A blocked draft still produces a payload, with an empty summary and the
    block reason attached. The alternative - returning nothing - would leave the
    console unable to show the merchant why filing did not happen.
    """
    body = dict(package_payload)
    body["amount"] = amount_minor
    body["summary"] = draft.summary
    body["action"] = "draft"
    if draft.blocked:
        body["blocked_reason"] = draft.block_reason
    return body
