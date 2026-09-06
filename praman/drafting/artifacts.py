"""Artifact field values, so grounding has something to resolve against.

**What this is, stated before anything uses it.** The corpus records which
evidence fields were present for a dispute, not what was written inside each
document - `data/generator/build.py` never had a reason to invent a courier's
signature block. Grounding needs the inside of the document: a verifier that
resolves `art_ship_7f2.delivered_at` needs that field to hold a date.

So this module deterministically derives field values for the artifacts a case
already has, seeded by `dispute_id`. The values are synthetic, exactly as the
disputes they belong to are synthetic, and they are internally consistent with
the case - a delivery lands between the payment and the dispute, an amount
matches the disputed amount.

**What it is not.** It is not retrieval, and nothing here claims a real courier
API would return these. Its only job is to give the verifier real field values
to check real citations against, so that grounding is a mechanism rather than a
diagram. The verifier is indifferent to where artifacts came from, which is why
it can be tested independently of this file.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any

from praman.evidence.types import EvidenceArtifact

# Which fields each evidence document carries. Mirrors the sentence templates in
# `provider.py`: a drafter can only cite what retrieval actually extracted.
_SCHEMA: dict[str, tuple[str, ...]] = {
    "shipping_proof": ("delivered_at", "signed_by", "tracking_id", "carrier"),
    "billing_proof": ("amount", "authorised_at", "reference"),
    "customer_communication": ("channel", "last_message_at", "message_count"),
    "proof_of_service": ("rendered_at", "reference"),
    "access_activity_log": ("last_access_at", "access_count"),
    "refund_confirmation": ("amount", "refunded_at", "reference"),
    "refund_cancellation_policy": ("published_at", "url"),
    "term_and_conditions": ("published_at", "url"),
    "cancellation_proof": ("cancelled_at", "reference"),
    "explanation_letter": ("written_at",),
}

_CARRIERS = ("Delhivery", "Blue Dart", "Ecom Express", "XpressBees", "Shadowfax")
_SIGNATORIES = ("the cardholder", "a resident at the address", "the registered recipient")


def _seed(dispute_id: str, api_field: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(f"{dispute_id}|{api_field}".encode(), digest_size=8).digest(), "big"
    )


def _artifact_id(dispute_id: str, api_field: str) -> str:
    tag = hashlib.blake2b(f"{dispute_id}|{api_field}".encode(), digest_size=4).hexdigest()
    return f"art_{api_field.replace('others.', 'oth_')[:12]}_{tag}"


def synthesize(
    dispute_id: str,
    api_fields: tuple[str, ...] | list[str],
    *,
    created_at: str,
    payment_created_at: str,
    amount_minor: int,
    channel: str = "email",
) -> dict[str, EvidenceArtifact]:
    """Build one artifact per present evidence field, with consistent values.

    Timeline consistency is not decoration: the constraint layer already refuses
    a delivery that post-dates its dispute, so values that ignored the timeline
    would produce artifacts the rest of the system would rightly reject.
    """
    paid = datetime.fromisoformat(payment_created_at)
    disputed = datetime.fromisoformat(created_at)
    window = max((disputed - paid).total_seconds(), 3600.0)

    artifacts: dict[str, EvidenceArtifact] = {}
    for api_field in api_fields:
        rng = random.Random(_seed(dispute_id, api_field))
        # Everything happens between payment and dispute, which is the only
        # ordering the constraints will accept.
        when = paid + timedelta(seconds=window * rng.uniform(0.05, 0.85))
        stamp = when.date().isoformat()
        reference = f"{api_field[:3].upper()}{rng.randint(10**7, 10**8 - 1)}"

        values: dict[str, Any] = {
            "delivered_at": stamp,
            "signed_by": rng.choice(_SIGNATORIES),
            "tracking_id": f"{rng.choice(_CARRIERS)[:3].upper()}{rng.randint(10**8, 10**9 - 1)}",
            "carrier": rng.choice(_CARRIERS),
            "amount": f"Rs {amount_minor // 100:,}",
            "authorised_at": paid.date().isoformat(),
            "reference": reference,
            "channel": channel,
            "last_message_at": stamp,
            "message_count": rng.randint(2, 14),
            "rendered_at": stamp,
            "last_access_at": stamp,
            "access_count": rng.randint(1, 40),
            "refunded_at": stamp,
            "published_at": (paid - timedelta(days=rng.randint(30, 400))).date().isoformat(),
            "url": f"https://merchant.example/{api_field.replace('_', '-')}",
            "cancelled_at": stamp,
            "written_at": disputed.date().isoformat(),
            "retrieved_at": disputed.date().isoformat(),
        }
        fields = {f: values[f] for f in _SCHEMA.get(api_field, ("retrieved_at",)) if f in values}
        fields.setdefault("retrieved_at", disputed.date().isoformat())

        artifact_id = _artifact_id(dispute_id, api_field)
        artifacts[artifact_id] = EvidenceArtifact(
            artifact_id=artifact_id,
            source_system="merchant_records",
            artifact_type=api_field,
            api_field=api_field,
            content_hash=hashlib.blake2b(
                f"{dispute_id}|{api_field}|{sorted(fields.items())}".encode(), digest_size=16
            ).hexdigest(),
            retrieved_at=disputed.isoformat(),
            fields=fields,
        )
    return artifacts
