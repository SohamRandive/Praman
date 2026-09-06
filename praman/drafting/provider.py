"""The drafting model sits behind this interface, and holds nothing else.

No tools, no retrieval, no web access, no write authority. It receives the
assembled `EvidencePackage` and structured case fields, and returns `Claim`
objects. Contest-versus-accept was already decided, in Python, by an inequality
it never saw.

The interface is the point: nothing downstream knows or cares which
implementation produced the claims, because everything downstream re-checks
them against the artifacts anyway. A provider that lies is a provider whose
sentences get stripped.

Two implementations ship:

* `TemplatedProvider` - deterministic, grounded by construction. This is what
  runs in tests, in CI, in `make draft` and in the console fixtures, and it
  needs no credentials and no network.
* `FaultInjectingProvider` - deliberately emits the failure modes a generative
  drafter exhibits, so the verifier's behaviour can be demonstrated rather than
  asserted.

**On `FaultInjectingProvider`, stated plainly because it would be easy to
misread.** It is fault injection against our own verifier. It is NOT a
measurement of any model's hallucination rate, and nothing in this repository
claims one. No hosted model is wired up here, so no such rate has been
observed. What the failure story in the README shows is that *this class of
error is caught*, which is a claim about the verifier and is the claim being
made.
"""

from __future__ import annotations

import random
from typing import Any, Protocol

from praman.evidence.engine import label_for
from praman.evidence.types import EvidenceArtifact

from .types import Citation, Claim


class LLMProvider(Protocol):
    """What a hosted drafting model would implement.

    Swappable by design - nothing in the architecture depends on a specific
    one, and the grounding verifier downstream is what makes that safe rather
    than merely tidy.
    """

    name: str

    def draft(
        self,
        artifacts: dict[str, EvidenceArtifact],
        required: tuple[str, ...],
        case: dict[str, Any],
    ) -> list[Claim]: ...


# One sentence pattern per evidence field. Each names the fields it cites, so a
# claim can never be built without its citations - the schema makes an
# uncited sentence unrepresentable rather than merely discouraged.
_SENTENCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "shipping_proof": (
        "The consignment was delivered on {delivered_at} and signed for by {signed_by}, "
        "against tracking reference {tracking_id}.",
        ("delivered_at", "signed_by", "tracking_id"),
    ),
    "billing_proof": (
        "The transaction of {amount} was authorised on {authorised_at} "
        "under reference {reference}.",
        ("amount", "authorised_at", "reference"),
    ),
    "customer_communication": (
        "The cardholder was corresponded with by {channel} on {last_message_at}, "
        "and the thread is attached in full.",
        ("channel", "last_message_at"),
    ),
    "proof_of_service": (
        "The service was rendered on {rendered_at} and recorded under {reference}.",
        ("rendered_at", "reference"),
    ),
    "access_activity_log": (
        "The account was accessed from the cardholder's registered session on "
        "{last_access_at}, {access_count} times in the billing period.",
        ("last_access_at", "access_count"),
    ),
    "refund_confirmation": (
        "A refund of {amount} was processed on {refunded_at} under {reference}.",
        ("amount", "refunded_at", "reference"),
    ),
    "refund_cancellation_policy": (
        "The published refund and cancellation policy in force at the time of "
        "purchase was last updated on {published_at}.",
        ("published_at",),
    ),
    "term_and_conditions": (
        "The terms and conditions accepted at checkout were published on {published_at}.",
        ("published_at",),
    ),
    "cancellation_proof": (
        "The cancellation was recorded on {cancelled_at} under reference {reference}.",
        ("cancelled_at", "reference"),
    ),
    "explanation_letter": (
        "A merchant explanation letter dated {written_at} is attached.",
        ("written_at",),
    ),
}

_FALLBACK = ("The {label} is attached and was retrieved on {retrieved_at}.", ("retrieved_at",))


class TemplatedProvider:
    """Deterministic drafting, grounded by construction.

    Every sentence is assembled *from* the artifact field values it cites, so a
    fabricated value is not merely unlikely, it is unreachable: there is no path
    by which a number reaches the prose without coming out of a cited field.

    That makes this provider uninteresting as a hallucination risk and exactly
    right as the default. It is also why the verifier is still run over its
    output - a check that only runs against inputs you already trust is not a
    check, and a future provider swapped in behind the same interface will not
    have this property.
    """

    name = "templated"

    def draft(
        self,
        artifacts: dict[str, EvidenceArtifact],
        required: tuple[str, ...],
        case: dict[str, Any],
    ) -> list[Claim]:
        claims: list[Claim] = []
        for artifact in sorted(artifacts.values(), key=lambda a: a.artifact_id):
            template, field_names = _SENTENCES.get(artifact.api_field, _FALLBACK)
            usable = [f for f in field_names if f in artifact.fields]
            if not usable:
                continue

            values = {f: artifact.fields[f] for f in usable}
            try:
                text = template.format(label=label_for(artifact.api_field), **values)
            except KeyError:
                # A template whose fields did not all survive retrieval. Say
                # less rather than inventing the rest.
                text = _FALLBACK[0].format(
                    label=label_for(artifact.api_field),
                    retrieved_at=artifact.fields.get("retrieved_at", artifact.retrieved_at),
                )
                usable = [f for f in ("retrieved_at",) if f in artifact.fields]
                values = {f: artifact.fields[f] for f in usable}

            citations = tuple(Citation(artifact.artifact_id, f) for f in usable)
            claims.append(Claim(
                claim_id=f"clm_{artifact.artifact_id}",
                text=text,
                citations=citations,
                asserts={f"{artifact.artifact_id}.{f}": v for f, v in values.items()},
                api_field=artifact.api_field,
                required=artifact.api_field in required,
            ))
        return claims


class FaultInjectingProvider:
    """Emits the failure modes a generative drafter exhibits, on purpose.

    Exists so the verifier can be *demonstrated* rather than asserted. Seeded,
    so a caught fabrication is reproducible and a screenshot of it survives.

    Read the module docstring before quoting anything this produces: it is fault
    injection against our own verifier, not evidence about any model's error
    rate. None has been measured, because no hosted model is wired up.
    """

    name = "fault-injecting"

    #: The three ways a grounded-looking sentence is actually wrong.
    MODES = ("fabricated_value", "dangling_citation", "uncited_sentence")

    def __init__(self, seed: int = 20260904, rate: float = 0.35,
                 base: LLMProvider | None = None) -> None:
        self.seed = seed
        self.rate = rate
        self.base = base or TemplatedProvider()

    def draft(
        self,
        artifacts: dict[str, EvidenceArtifact],
        required: tuple[str, ...],
        case: dict[str, Any],
    ) -> list[Claim]:
        rng = random.Random(f"{self.seed}|{case.get('dispute_id', '')}")
        out: list[Claim] = []
        for claim in self.base.draft(artifacts, required, case):
            if rng.random() >= self.rate:
                out.append(claim)
                continue
            out.append(self._corrupt(claim, rng))
        return out

    def _corrupt(self, claim: Claim, rng: random.Random) -> Claim:
        mode = rng.choice(self.MODES)

        if mode == "uncited_sentence":
            # The classic: a fluent, plausible, entirely unsupported sentence.
            return Claim(
                claim_id=claim.claim_id,
                text="The cardholder confirmed receipt and raised no complaint at the time.",
                citations=(),
                asserts={},
                api_field=claim.api_field,
                required=claim.required,
            )

        if mode == "dangling_citation":
            # Cites a document that is not in the package - the shape of a model
            # remembering an artifact from a different case.
            return Claim(
                claim_id=claim.claim_id,
                text=claim.text,
                citations=(Citation("art_not_in_package", "delivered_at"),),
                asserts={},
                api_field=claim.api_field,
                required=claim.required,
            )

        # fabricated_value: real citations, real artifact, wrong date in the
        # prose. `asserts` stays consistent, so only the text scan catches it.
        # This is the one that would reach an issuer without check 3.
        import re as _re

        fabricated = f"20{rng.randint(24, 27)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        text, n = _re.subn(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", fabricated, claim.text, count=1)
        if n == 0:
            text = claim.text.rstrip(".") + f", confirmed on {fabricated}."
        return Claim(
            claim_id=claim.claim_id,
            text=text,
            citations=claim.citations,
            asserts=dict(claim.asserts),
            api_field=claim.api_field,
            required=claim.required,
        )
