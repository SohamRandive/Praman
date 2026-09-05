"""Hash-chained, append-only audit log.

`prev_hash` makes the log tamper-evident. Stated precisely, because the loose
version of this claim is wrong: editing a record breaks *that record's* hash
immediately, and `verify()` names it. What the chain adds is that the edit
cannot be repaired quietly - recomputing the record's hash changes the next
record's `prev_hash`, which changes its hash, and so on, so hiding one edit
means rewriting every record after it. Detection is local; forgery is not.

In a fintech review this costs twenty lines and buys enormous credibility,
which is why it is here rather than on a roadmap.

The log is the product. Every arrow in the architecture writes to it, including
the ones that failed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

GENESIS = "0" * 64


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    ts: str
    actor: str          # system | agent:{name} | human:{id}
    event: str
    inputs_hash: str
    outputs_hash: str
    prev_hash: str
    record_hash: str

    def as_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass
class AuditLog:
    records: list[AuditRecord] = field(default_factory=list)

    @property
    def head(self) -> str:
        return self.records[-1].record_hash if self.records else GENESIS

    def append(self, actor: str, event: str, inputs: Any = None, outputs: Any = None) -> AuditRecord:
        prev = self.head
        body = {
            "ts": datetime.now(UTC).isoformat(),
            "actor": actor,
            "event": event,
            "inputs_hash": _digest(inputs),
            "outputs_hash": _digest(outputs),
            "prev_hash": prev,
        }
        record = AuditRecord(**body, record_hash=_digest(body))
        self.records.append(record)
        return record

    def verify(self) -> list[str]:
        """Return the reasons the chain is broken, empty if intact."""
        problems: list[str] = []
        prev = GENESIS
        for i, r in enumerate(self.records):
            if r.prev_hash != prev:
                problems.append(f"record {i} ({r.event}): prev_hash does not match record {i - 1}")
            body = {
                "ts": r.ts, "actor": r.actor, "event": r.event,
                "inputs_hash": r.inputs_hash, "outputs_hash": r.outputs_hash,
                "prev_hash": r.prev_hash,
            }
            if _digest(body) != r.record_hash:
                problems.append(f"record {i} ({r.event}): contents do not match its hash")
            prev = r.record_hash
        return problems
