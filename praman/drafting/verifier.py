"""The grounding verifier. Deterministic, and the only thing standing between
a generated sentence and a bank.

Three checks, in order of how badly they fail:

1. **Resolution.** Every citation must point at an artifact that is actually in
   the package and a field that artifact actually carries. A claim citing
   nothing is malformed by schema, not merely unsupported.
2. **Assertion consistency.** The value the sentence reports for a citation must
   equal the value the artifact holds.
3. **Prose consistency.** Every value-shaped token in the sentence - a date, an
   amount, a tracking reference - must appear among the cited field values.

Check 3 is the one that earns its keep. A fabrication looks like a real
citation with a wrong date in the prose beside it: `asserts` stays consistent
because the generator never noticed it invented anything, and only scanning the
text catches it. Checks 1 and 2 alone would pass that sentence straight through
to an issuer.

No model runs in this file, and none ever will. A verifier that asks a model
whether a model hallucinated is not a verifier.
"""

from __future__ import annotations

import re
from typing import Any

from praman.evidence.types import EvidenceArtifact

from .types import Claim, Strip

# Value-shaped tokens worth checking. Deliberately narrow: these are the things
# an issuer checks and a generator invents. Ordinary prose ("the consignment was
# signed for") carries no checkable atom and is verified by its citations alone.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 2026-03-12, 2026/03/12
    ("date_iso", re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")),
    # 12 March 2026, 12 Mar 2026
    ("date_long", re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        re.I)),
    # Rs 18,400 / ₹18,400 / INR 18400
    ("amount", re.compile(r"(?:₹|\bRs\.?\s?|\bINR\s?)\s?[\d,]+(?:\.\d{2})?", re.I)),
    # Tracking / UTR / reference: 8+ chars, mixed letters and digits
    ("reference", re.compile(r"\b(?=[A-Z0-9_-]*\d)(?=[A-Z0-9_-]*[A-Z])[A-Z0-9_-]{8,}\b")),
)

# The trailing `\b` this once carried did not match after "Rs." - a full stop is
# already a non-word character, so there was no boundary to find, and "Rs. 18,400"
# normalised to ".18400" while the artifact held "18400". That stripped a TRUE
# sentence, which is the failure that gets a verifier switched off. The optional
# full stop is now consumed explicitly.
_NORMALISE = re.compile(r"[\s,₹]|\b(?:rs|inr)\b\.?", re.I)


def _normalise(value: Any) -> str:
    """Compare on content, not on formatting.

    "Rs 18,400", "₹18400" and "18400" are the same assertion, and a verifier
    that fails them apart would strip true sentences - which trains everyone to
    switch it off. Case, whitespace, separators and currency markers go; digits
    and letters stay.
    """
    return _NORMALISE.sub("", str(value)).strip().lower()


def _month_variants(text: str) -> set[str]:
    """`12 March 2026` and `2026-03-12` are the same date to a reader and to an
    issuer, so they must be the same date here."""
    months = ("jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec")
    out = {_normalise(text)}
    m = re.match(r"(\d{1,2})\s+([a-z]{3})[a-z]*\s+(\d{4})", text.strip(), re.I)
    if m:
        day, mon, year = m.group(1), m.group(2).lower(), m.group(3)
        if mon in months:
            out.add(f"{year}-{months.index(mon) + 1:02d}-{int(day):02d}")
    m = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", text.strip())
    if m:
        year, mon, day = m.groups()
        out.add(f"{int(day)}{months[int(mon) - 1]}{year}")
    return {v.replace("-", "").replace("/", "") for v in out} | out


def checkable_values(text: str) -> list[tuple[str, str]]:
    """Value-shaped tokens in a sentence, as (kind, raw) pairs."""
    found: list[tuple[str, str]] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            found.append((kind, match.group(0).strip()))
    return found


def verify_claim(
    claim: Claim, artifacts: dict[str, EvidenceArtifact]
) -> Strip | None:
    """Return the reason this claim must be stripped, or None if it survives."""
    if not claim.grounded_by_schema:
        return Strip(claim.claim_id, claim.text, "no_citation",
                     "the sentence cites no artifact field")

    cited_values: list[str] = []
    for citation in claim.citations:
        artifact = artifacts.get(citation.artifact_id)
        if artifact is None:
            return Strip(claim.claim_id, claim.text, "unresolved_artifact",
                         f"{citation.ref} - no such artifact in the package")
        if citation.field_name not in artifact.fields:
            return Strip(claim.claim_id, claim.text, "unresolved_field",
                         f"{citation.ref} - the artifact carries no such field")

        actual = artifact.fields[citation.field_name]
        cited_values.append(str(actual))

        stated = claim.asserts.get(citation.ref)
        if stated is not None and _normalise(stated) != _normalise(actual):
            return Strip(claim.claim_id, claim.text, "value_mismatch",
                         f"{citation.ref} states {stated!r}, artifact holds {actual!r}")

    # Prose consistency. Every checkable atom in the sentence must be present in
    # something it cited - this is where a fabricated date is caught.
    supported: set[str] = set()
    for value in cited_values:
        supported |= _month_variants(value)
        supported.add(_normalise(value))
    for kind, raw in checkable_values(claim.text):
        variants = _month_variants(raw) | {_normalise(raw)}
        if not (variants & supported):
            return Strip(
                claim.claim_id, claim.text, "unsupported_value",
                f"{kind} {raw!r} appears in no cited field "
                f"(cited: {', '.join(c.ref for c in claim.citations)})",
            )
    return None


def coverage(claims: list[Claim], required: tuple[str, ...]) -> tuple[float, tuple[str, ...]]:
    """Share of required fields still spoken to by at least one surviving claim.

    This is the number that decides block-versus-emit. Coverage is measured over
    REQUIRED fields only: losing a supporting sentence weakens a narrative,
    losing the only sentence about the delivery proof removes the case.
    """
    if not required:
        return 1.0, ()
    covered = tuple(sorted({c.api_field for c in claims if c.api_field in required}))
    return round(len(covered) / len(required), 6), covered


def verify(
    claims: list[Claim],
    artifacts: dict[str, EvidenceArtifact],
    required: tuple[str, ...],
) -> tuple[list[Claim], list[Strip], float, float, tuple[str, ...]]:
    """Strip what cannot be grounded, then report what that cost.

    Returns (survivors, strips, coverage_before, coverage_after, covered).
    Blocking is decided by the caller, because the threshold is a policy choice
    and this function is a measurement.
    """
    before, _ = coverage(claims, required)
    survivors: list[Claim] = []
    strips: list[Strip] = []
    for claim in claims:
        strip = verify_claim(claim, artifacts)
        if strip is None:
            survivors.append(claim)
        else:
            strips.append(strip)
    after, covered = coverage(survivors, required)
    return survivors, strips, before, after, covered
