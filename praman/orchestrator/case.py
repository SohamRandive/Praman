"""The CaseFile: what every agent writes into and the adjudicator reads from."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from praman.audit import AuditLog
from praman.orchestrator.contract import AgentResult


def case_id_for(dispute_id: str) -> str:
    """Derived from `dispute_id`, so a replayed webhook resolves to the same case.

    Idempotency is a property of the identifier rather than of a lookup, which
    means a duplicate delivery cannot create a second package even if it races
    the first.
    """
    return "case_" + hashlib.blake2b(dispute_id.encode(), digest_size=10).hexdigest()


@dataclass
class CaseFile:
    dispute_id: str
    merchant_id: str
    reason_code: str
    amount_minor: int
    respond_by: str
    created_at: str
    payment: dict[str, Any] = field(default_factory=dict)
    order: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    agent_results: dict[str, AgentResult] = field(default_factory=dict)
    decision: Any = None
    package: Any = None
    audit: AuditLog = field(default_factory=AuditLog)

    @property
    def case_id(self) -> str:
        return case_id_for(self.dispute_id)

    @property
    def degraded_agents(self) -> list[str]:
        return sorted(
            name for name, r in self.agent_results.items() if r.status != "ok"
        )

    @property
    def missing(self) -> list[str]:
        """Agents whose output the adjudicator does not have.

        Passed to the model as explicit missingness indicators rather than
        silently filled with zeros - "we could not reach the courier API" is
        itself predictive.
        """
        return sorted(
            name for name, r in self.agent_results.items() if not r.usable
        )

    def payload(self, agent: str, key: str, default: Any = None) -> Any:
        result = self.agent_results.get(agent)
        if result is None or not result.usable:
            return default
        return result.payload.get(key, default)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CaseFile:
        return cls(
            dispute_id=row["dispute_id"],
            merchant_id=row["merchant_id"],
            reason_code=row["reason_code"],
            amount_minor=row["amount_minor"],
            respond_by=row["respond_by"],
            created_at=row["created_at"],
            payment={
                "amount_minor": row["amount_minor"],
                "created_at": row["payment_created_at"],
                "captured": row["payment_captured"],
            },
            order={},
            raw=row,
        )
