"""The five agents.

Each is deliberately thin: this phase is about the *contract* and the failure
behaviour, not about the retrieval. Each one reads a different source, fails
differently, and degrades rather than raising.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from typing import Any

from praman.drafting import synthesize
from praman.evidence import CaseContext, Classification
from praman.evidence.engine import label_for
from praman.orchestrator.contract import AgentResult


def stable_key(seed: int, dispute_id: str) -> int:
    """Process-stable seed. Python's hash() is randomised per run for strings."""
    return int.from_bytes(
        hashlib.blake2b(f"{seed}|{dispute_id}".encode(), digest_size=8).digest(), "big"
    )


class EvidenceRetrieval:
    """I/O bound. Walks the merchant's connected sources and binds artifacts.

    Degraded: returns whatever answered and marks the rest unavailable, so the
    package is reported incomplete rather than silently weak.

    **Retrieval is stubbed in this phase and reads the corpus's recorded
    verdict.** The corpus does not persist per-artifact field values, only which
    fields were present, so re-deriving here would evaluate every constraint
    against empty artifacts and report "cannot verify" on cases the engine
    already resolved. That would be a worse lie than the stub. The verdict it
    returns is the real evidence engine's - computed by the same code at
    generation time - and what this phase is actually testing is the agent
    contract and the failure behaviour, not the retrieval.
    """

    name = "evidence"

    def __init__(
        self,
        matrix,
        delay_ms: int = 0,
        drop_rate: float = 0.0,
        seed: int = 20260904,
    ) -> None:
        """`drop_rate` simulates partial retrieval: the share of otherwise
        available fields that a source failed to return this time.

        This is the agent's entire reason for existing. Total failure is the
        easy case and it is already tested; the realistic case is that the
        courier API answers, the support desk times out, and the package has to
        be scored on what came back rather than on what exists. Seeded, so a
        degraded run is as reproducible as a clean one.
        """
        self.matrix = matrix
        self.delay_ms = delay_ms
        self.drop_rate = drop_rate
        self.seed = seed

    def _retrieve(self, row: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Which fields came back, and which the sources failed to return."""
        available = tuple(row["evidence_fields_present"])
        if self.drop_rate <= 0 or not available:
            return available, ()
        rng = random.Random(stable_key(self.seed, row["dispute_id"]))
        kept, lost = [], []
        for field_name in available:
            (lost if rng.random() < self.drop_rate else kept).append(field_name)
        return tuple(kept), tuple(lost)

    async def run(self, case: Any, budget_ms: int) -> AgentResult:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        row = case.raw
        context = CaseContext(
            dispute={"amount_minor": case.amount_minor, "created_at": case.created_at},
            payment=case.payment,
            order=case.order,
        )
        classification = (
            Classification(row["resolved_code"], row["classification_confidence"])
            if row.get("classification_confidence") is not None
            else None
        )
        reqs = self.matrix.resolve(case.reason_code, context, classification)
        retrieved, unavailable = self._retrieve(row)

        # Artifacts carry the field VALUES, which is what the grounding verifier
        # resolves citations against. Only fields that actually came back get an
        # artifact: a document the courier API would not return today cannot be
        # cited in a draft filed today.
        artifacts = synthesize(
            row["dispute_id"], retrieved,
            created_at=case.created_at,
            payment_created_at=case.payment.get("created_at", case.created_at),
            amount_minor=case.amount_minor,
            channel=row.get("comms_channel", "email"),
        )

        if not unavailable:
            return AgentResult(self.name, "ok", 0, {
                "requirements": reqs,
                "sufficient": bool(row["evidence_sufficient"]),
                "completeness": row["completeness_score"],
                "required_coverage": row["required_coverage"],
                "blocking_gaps": tuple(row["blocking_gaps"]),
                "fields_present": retrieved,
                "unavailable": (),
                "routing": row["routing"],
                "artifacts": artifacts,
            })

        # Partial retrieval. The package is re-scored on what CAME BACK, never
        # on what exists somewhere - a field the merchant has but the courier
        # API would not return today is a field that cannot be filed today.
        required = set(reqs.required)
        supporting = set(reqs.supporting)
        got_required = required & set(retrieved)
        missing_required = sorted(required - set(retrieved))
        req_w = float(self.matrix.scoring.get("required_weight", 1.0))
        sup_w = float(self.matrix.scoring.get("supporting_weight", 0.3))
        total = req_w * len(required) + sup_w * len(supporting)
        earned = req_w * len(got_required) + sup_w * len(supporting & set(retrieved))

        gaps = tuple(
            f"No {label_for(f)}. (source unavailable at retrieval time)"
            for f in missing_required
        ) + tuple(g for g in row["blocking_gaps"] if not g.startswith("No "))

        return AgentResult(
            self.name,
            "degraded",
            0,
            {
                "requirements": reqs,
                "sufficient": bool(row["evidence_sufficient"]) and not missing_required,
                "completeness": round(earned / total, 6) if total else 1.0,
                "required_coverage": (
                    round(len(got_required) / len(required), 6) if required else 1.0
                ),
                "blocking_gaps": gaps,
                "fields_present": retrieved,
                "unavailable": unavailable,
                "routing": "blocked" if missing_required else row["routing"],
                "artifacts": artifacts,
            },
            confidence=round(1.0 - len(unavailable) / max(len(row["evidence_fields_present"]), 1), 4),
            errors=tuple(f"{f}: source did not respond" for f in unavailable),
        )


class NetworkForensics:
    """CPU/graph bound. Component statistics from the salted entity graph.

    Degraded: falls back to local neighbourhood statistics if the component
    lookup is unavailable. Never blocks the decision on graph work.
    """

    name = "network"

    def __init__(self, components: dict[str, dict[str, float]]) -> None:
        self.components = components

    async def run(self, case: Any, budget_ms: int) -> AgentResult:
        stats = self.components.get(case.dispute_id)
        if stats is None:
            return AgentResult(self.name, "degraded", 0, {"component": {}},
                               confidence=0.3,
                               errors=("no component statistics for this dispute",))
        return AgentResult(self.name, "ok", 0, {"component": stats})


class PrecedentRecall:
    """Vector-search bound. Comparable resolved cases with known outcomes.

    This is what makes the win probability explainable: "of 41 comparable 13.1
    cases with signed delivery proof, 34 were won."
    """

    name = "precedent"

    def __init__(self, history: dict[tuple[str, bool], tuple[int, int]]) -> None:
        self.history = history

    async def run(self, case: Any, budget_ms: int) -> AgentResult:
        key = (case.reason_code, bool(case.raw.get("no_blocking_gaps")))
        comparable = self.history.get(key)
        if comparable is None:
            return AgentResult(self.name, "degraded", 0, {}, confidence=0.0,
                               errors=("no comparable cases for this descriptor",))
        won, total = comparable
        return AgentResult(self.name, "ok", 0, {"comparable": (won, total)})


class PolicyCompliance:
    """Fully deterministic. No model, and never will be.

    The reference against which everything else is checked.
    """

    name = "policy"

    async def run(self, case: Any, budget_ms: int) -> AgentResult:
        from datetime import datetime

        respond_by = datetime.fromisoformat(case.respond_by)
        created = datetime.fromisoformat(case.created_at)
        hours = (respond_by - created).total_seconds() / 3600
        return AgentResult(self.name, "ok", 0, {
            "deadline_feasible": hours > 4,
            "hours_remaining": hours,
            "at_risk": hours <= 24,
        })


class MerchantContext:
    """SQL bound. Category, dispute-ratio trend, historical loss patterns.

    Exists so the product can say the honest thing: sometimes the correct
    recommendation is accept, because the merchant's real problem is a courier.
    """

    name = "merchant"

    def __init__(self, profiles: dict[str, dict[str, Any]]) -> None:
        self.profiles = profiles

    async def run(self, case: Any, budget_ms: int) -> AgentResult:
        profile = self.profiles.get(case.merchant_id)
        if profile is None:
            return AgentResult(self.name, "degraded", 0, {}, confidence=0.0,
                               errors=("merchant profile unavailable",))
        return AgentResult(self.name, "ok", 0, {
            "archetype": profile["archetype"],
            "dispute_rate": profile["dispute_rate"],
        })
