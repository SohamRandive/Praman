"""Ring detection: two stages, because one alone gives noise or nothing.

**Stage one, candidate generation** (`graph.components`) is connected components
over shared salted entities. Cheap, high recall, deliberately over-inclusive. A
family sharing one address and one device is a component here, and nothing at
this stage tries to tell it apart from a device farm.

**Stage two, cohesion scoring** is this file. Rings burst; households do not.
The discriminating signals are temporal concentration, merchant span, reason-code
homogeneity and disputes per member - not structure, which the two share by
construction (ADR-006).

Reporting an innocent household as a fraud ring is the worst false positive this
system can produce, so the threshold is set to hold precision on held-out data
and **false-ring rate is reported separately** rather than folded into an
aggregate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .graph import components

MIN_MEMBERS = 2
MIN_DISPUTES = 3


@dataclass(frozen=True)
class Candidate:
    component_id: str
    identities: tuple[str, ...]
    dispute_ids: tuple[str, ...]
    merchants: tuple[str, ...]
    split: str
    n_members: int
    n_disputes: int
    active_days: float
    disputes_per_day: float
    disputes_per_member: float
    merchant_span: int
    code_homogeneity: float

    def features(self) -> dict[str, float]:
        return {
            "disputes_per_day": self.disputes_per_day,
            "disputes_per_member": self.disputes_per_member,
            "merchant_span": float(self.merchant_span),
            "code_homogeneity": self.code_homogeneity,
            "n_members": float(self.n_members),
        }


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v)


def candidates(
    disputes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[Candidate]:
    """Stage one plus the statistics stage two scores. Over-inclusive by design."""
    comp_of = components(edges)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in disputes:
        grouped[comp_of.get(d["identity_hash"], d["identity_hash"])].append(d)

    out: list[Candidate] = []
    for comp, rows in grouped.items():
        identities = {r["identity_hash"] for r in rows}
        if len(identities) < MIN_MEMBERS or len(rows) < MIN_DISPUTES:
            continue
        times = sorted(_ts(r["created_at"]) for r in rows)
        active = max((times[-1] - times[0]).total_seconds() / 86400.0, 1.0)
        codes = {r["reason_code"] for r in rows}
        out.append(Candidate(
            component_id=comp,
            identities=tuple(sorted(identities)),
            dispute_ids=tuple(sorted(r["dispute_id"] for r in rows)),
            merchants=tuple(sorted({r["merchant_id"] for r in rows})),
            split=rows[0]["split"],
            n_members=len(identities),
            n_disputes=len(rows),
            active_days=active,
            disputes_per_day=len(rows) / active,
            disputes_per_member=len(rows) / len(identities),
            merchant_span=len({r["merchant_id"] for r in rows}),
            code_homogeneity=len(rows) / len(codes),
        ))
    return sorted(out, key=lambda c: c.component_id)


def cohesion(c: Candidate) -> float:
    """A transparent score, not a model.

    Five terms a human can argue with, each capped so no single one can carry a
    decision alone. Burst rate dominates because it is what actually separates a
    ring from a household: both share entities, both span merchants, and only
    one of them files in a hurry.
    """
    burst = min(c.disputes_per_day / 1.0, 1.0)
    volume = min(c.disputes_per_member / 4.0, 1.0)
    span = min(max(c.merchant_span - 1, 0) / 5.0, 1.0)
    homogeneity = min(max(c.code_homogeneity - 1.0, 0.0) / 3.0, 1.0)
    scale = min(max(c.n_members - 1, 0) / 8.0, 1.0)
    return round(
        0.45 * burst + 0.20 * volume + 0.15 * span + 0.10 * homogeneity + 0.10 * scale, 6
    )


def choose_threshold(
    scored: list[tuple[Candidate, float]], labels: dict[str, bool], target_precision: float
) -> float:
    """Lowest threshold that still holds the precision floor on held-out data.

    Precision first, recall second. A missed ring costs one merchant one
    dispute; a household reported as a fraud ring is the worst error this system
    can make, which is why the floor is a constraint rather than a trade-off.
    """
    best = 1.01
    for _, s in sorted(scored, key=lambda kv: -kv[1]):
        flagged = [(c, sc) for c, sc in scored if sc >= s]
        tp = sum(1 for c, _ in flagged if labels.get(c.component_id, False))
        precision = tp / len(flagged) if flagged else 0.0
        if precision >= target_precision and tp:
            best = s
    return best


def evaluate(
    scored: list[tuple[Candidate, float]], labels: dict[str, bool], threshold: float
) -> dict[str, float]:
    flagged = [c for c, s in scored if s >= threshold]
    positives = [c for c, _ in scored if labels.get(c.component_id, False)]
    negatives = [c for c, _ in scored if not labels.get(c.component_id, False)]
    tp = sum(1 for c in flagged if labels.get(c.component_id, False))
    fp = len(flagged) - tp
    return {
        "threshold": threshold,
        "candidates": float(len(scored)),
        "rings": float(len(positives)),
        "decoys": float(len(negatives)),
        "flagged": float(len(flagged)),
        "precision": tp / len(flagged) if flagged else 0.0,
        "recall": tp / len(positives) if positives else 0.0,
        # Reported separately and never folded into an aggregate: the share of
        # innocent clusters this system would accuse.
        "false_ring_rate": fp / len(negatives) if negatives else 0.0,
        "false_rings": float(fp),
    }
