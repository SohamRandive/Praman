"""Entity graph and point-in-time component features.

Every feature here must be computable by a production system *at the moment the
dispute arrives*. Two constraints follow, and both were violated by the first
version of the feature layer:

**Derived, not declared.** Cluster membership comes from connected components
over shared salted entities, not from the corpus's own group construction.
Reading `group_size` off the generator hands the model perfect knowledge of a
structure the production system would have to infer, which silently converts a
network ablation into a measurement of oracle knowledge.

**Point-in-time.** A component's statistics count only disputes that had already
happened. Counting the whole component's lifetime lets a dispute see its own
future - the ring's later activity is not evidence available when the first
claim lands.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self._parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:  # path compression
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[max(ra, rb)] = min(ra, rb)  # deterministic root


def components(edges: list[dict[str, Any]]) -> dict[str, str]:
    """Identity hash -> component id, from shared device / address / instrument.

    Deliberately over-inclusive: this is candidate generation, stage one of two.
    A household and a device farm are both connected components here, and
    nothing in this function tries to tell them apart. That is cohesion
    scoring's job, and conflating the two stages is how ring detectors end up
    reporting families as fraud.
    """
    uf = UnionFind()
    by_entity: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        uf.add(e["src"])
        by_entity[e["dst"]].append(e["src"])
    for identities in by_entity.values():
        first = identities[0]
        for other in identities[1:]:
            uf.union(first, other)
    return {identity: uf.find(identity) for identity in uf._parent}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def point_in_time_features(
    disputes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, dict[str, float]]:
    """Per dispute id, the component statistics knowable when it arrived.

    The graph is rebuilt incrementally in event order rather than queried as a
    finished object. An earlier version computed membership from the *final*
    graph, so `component_size` counted identities that had not yet transacted -
    a dispute could see how large its ring would eventually become. That leak is
    invisible in every metric, because it makes the features better rather than
    inconsistent, which is exactly why it needs an asserted invariant and not a
    comment.

    Semantics: when a dispute arrives, the system knows that claimant's own
    identity and entities (they are on the order), so its edges are added before
    its features are read. It does not know anything about later disputes, so
    component history counts strictly earlier ones.
    """
    # Which entities each identity touches, and when that first became visible.
    touches: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        touches[e["src"]].append(e["dst"])

    uf = UnionFind()
    entity_members: dict[str, list[str]] = defaultdict(list)
    seen_identities: set[str] = set()
    per_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)

    ordered = sorted(disputes, key=lambda d: (d["created_at"], d["dispute_id"]))
    out: dict[str, dict[str, float]] = {}

    for d in ordered:
        identity = d["identity_hash"]

        # 1. Admit this claimant's own linkage - known at arrival.
        if identity not in seen_identities:
            seen_identities.add(identity)
            uf.add(identity)
            for entity in touches.get(identity, ()):
                for other in entity_members[entity]:
                    uf.union(identity, other)
                entity_members[entity].append(identity)

        # 2. Read the component as it stands NOW, over identities already seen.
        root = uf.find(identity)
        members = [i for i in seen_identities if uf.find(i) == root]
        prior = [p for m in members for p in per_identity[m]]

        if prior:
            first = min(_ts(p["created_at"]) for p in prior)
            span_days = max((_ts(d["created_at"]) - first).total_seconds() / 86400.0, 1.0)
            merchants = {p["merchant_id"] for p in prior}
            identities = {p["identity_hash"] for p in prior}
            codes = {p["reason_code"] for p in prior}
            rate = len(prior) / span_days
        else:
            span_days, merchants, identities, codes, rate = 1.0, set(), set(), set(), 0.0

        size = float(len(members))
        out[d["dispute_id"]] = {
            "component_size": size,
            "component_shares_entity": float(size > 1),
            "component_prior_disputes": float(len(prior)),
            "component_prior_merchants": float(len(merchants)),
            "component_prior_identities": float(len(identities)),
            "component_disputes_per_day": float(rate),
            "component_active_days": float(span_days if prior else 0.0),
            # Reason-code homogeneity: a ring runs the same play repeatedly.
            "component_code_concentration": float(len(prior)) / len(codes) if codes else 0.0,
            # Disputes per member: separates a busy household from a farm.
            "component_disputes_per_member": float(len(prior)) / size,
        }

        # 3. Only now does this dispute become history for the next one.
        per_identity[identity].append(d)

    return out


COMPONENT_FEATURES = (
    "component_size",
    "component_shares_entity",
    "component_prior_disputes",
    "component_prior_merchants",
    "component_prior_identities",
    "component_disputes_per_day",
    "component_active_days",
    "component_code_concentration",
    "component_disputes_per_member",
)

EMPTY = dict.fromkeys(COMPONENT_FEATURES, 0.0)
