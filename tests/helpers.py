"""Fixtures shared across the evidence tests."""

from __future__ import annotations

from praman.evidence import CaseContext, EvidenceArtifact


def artifact(api_field: str, aid: str | None = None, **fields) -> EvidenceArtifact:
    return EvidenceArtifact(
        artifact_id=aid or f"doc_{api_field.replace('.', '_')}",
        source_system="test",
        artifact_type=api_field,
        api_field=api_field,
        content_hash="0" * 16,
        retrieved_at="2026-03-20T10:00:00+05:30",
        fields=fields,
    )


def context(**kw) -> CaseContext:
    dispute = {"amount_minor": 1_840_000, "created_at": "2026-03-18T11:00:00+05:30"}
    payment = {"amount_minor": 1_840_000, "created_at": "2026-03-01T09:00:00+05:30"}
    order = {"sla_due_at": "2026-03-10T20:00:00+05:30"}
    dispute.update(kw.pop("dispute", {}))
    payment.update(kw.pop("payment", {}))
    order.update(kw.pop("order", {}))
    return CaseContext(
        dispute=dispute, payment=payment, order=order, merchant=kw.pop("merchant", {})
    )
