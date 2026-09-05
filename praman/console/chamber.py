"""Export the entity graph for the network chamber.

Node kind is carried explicitly because the chamber distinguishes kinds by
*geometry*, not colour - colour is reserved for risk state, so it stays legible
to a colour-blind reader and in greyscale.

Every node also carries `t`, the day within the corpus window at which it first
appears. That is what the time scrubber replays: a ring assembling out of orders
that looked unrelated when they happened.

    python3 -m praman.console.chamber --out web/src/graph.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from praman.network.rings import candidates, choose_threshold, cohesion

ROOT = Path(__file__).resolve().parents[2]
KINDS = {"identity": 0, "device": 1, "address_geo": 2, "instrument": 3}


def build(corpus: Path, split: str = "test", max_nodes: int = 4200) -> dict[str, Any]:
    def read(name: str) -> list[dict[str, Any]]:
        with open(corpus / name, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    rows, edges = read("disputes.jsonl"), read("entity_edges.jsonl")
    groups = {g["group_id"]: g for g in read("groups.jsonl")}

    cands = candidates(rows, edges)
    by_disp = {r["dispute_id"]: r for r in rows}
    labels, profile = {}, {}
    for c in cands:
        gids = {by_disp[d]["group_id"] for d in c.dispute_ids if by_disp[d]["group_id"]}
        labels[c.component_id] = any(groups[g]["is_abusive"] for g in gids)
        profile[c.component_id] = sorted({groups[g]["profile"] for g in gids})[0] if gids else ""

    scored = [(c, cohesion(c)) for c in cands]
    threshold = choose_threshold(
        [(c, s) for c, s in scored if c.split == "calibration"], labels, 0.85)

    # The chamber shows one split's clusters. Solo claimants are the bulk of the
    # corpus and contribute nothing to a ring view, so they are excluded rather
    # than rendered as thousands of unconnected dots.
    keep = [(c, s) for c, s in scored if c.split == split]
    keep.sort(key=lambda cs: -cs[0].n_disputes)

    start = min(datetime.fromisoformat(r["created_at"]) for r in rows)
    first_seen: dict[str, float] = {}
    entity_merchants: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        day = (datetime.fromisoformat(r["created_at"]) - start).total_seconds() / 86400
        for key in (r["identity_hash"], r["device_hash"], r["address_hash"], r["instrument_hash"]):
            first_seen[key] = min(first_seen.get(key, day), day)
            entity_merchants[key].add(r["merchant_id"])

    identity_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in edges:
        identity_edges[e["src"]].append(e)

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    clusters: list[dict[str, Any]] = []

    def add(node_id: str, kind: str, cluster: int, risk: str) -> int:
        if node_id in index:
            return index[node_id]
        index[node_id] = len(nodes)
        nodes.append({
            "id": node_id,
            "kind": KINDS[kind],
            "cluster": cluster,
            "risk": risk,
            "t": round(first_seen.get(node_id, 0.0), 2),
            "merchants": len(entity_merchants.get(node_id, ())),
        })
        return index[node_id]

    for ci, (c, score) in enumerate(keep):
        if len(nodes) > max_nodes:
            break
        abusive = labels[c.component_id]
        flagged = score >= threshold
        # Risk state is a claim the DETECTOR makes, never the ground truth. The
        # chamber must show what the system decided so a false ring is visible
        # as a mistake rather than quietly recoloured to look correct.
        risk = "flagged" if flagged else "cleared"
        clusters.append({
            "i": ci,
            "component": c.component_id,
            "flagged": flagged,
            "abusive": abusive,
            "correct": flagged == abusive,
            "profile": profile[c.component_id],
            "score": round(score, 3),
            "members": c.n_members,
            "disputes": c.n_disputes,
            "merchants": c.merchant_span,
            "per_day": round(c.disputes_per_day, 2),
            "days": round(c.active_days, 1),
        })
        for identity in c.identities:
            src = add(identity, "identity", ci, risk)
            for e in identity_edges.get(identity, ()):
                dst = add(e["dst"], e["dst_kind"], ci, risk)
                links.append({"s": src, "t": dst, "cluster": ci,
                              "when": round(max(nodes[src]["t"], nodes[dst]["t"]), 2)})

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "threshold": round(threshold, 3),
        "split": split,
        "window_days": round(
            max(n["t"] for n in nodes) if nodes else 0.0, 1),
        "kinds": {v: k for k, v in KINDS.items()},
        "summary": {
            "clusters": len(clusters),
            "rings": sum(1 for c in clusters if c["abusive"]),
            "decoys": sum(1 for c in clusters if not c["abusive"]),
            "flagged": sum(1 for c in clusters if c["flagged"]),
            "false_rings": sum(1 for c in clusters if c["flagged"] and not c["abusive"]),
            "missed": sum(1 for c in clusters if not c["flagged"] and c["abusive"]),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--out", default=str(ROOT / "web" / "src" / "graph.json"))
    ap.add_argument("--split", default="test")
    args = ap.parse_args(argv)

    graph = build(Path(args.corpus), args.split)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, separators=(",", ":"))
    s = graph["summary"]
    print(f"wrote {len(graph['nodes'])} nodes, {len(graph['links'])} links to {out}")
    print(f"  {s['clusters']} clusters: {s['rings']} rings, {s['decoys']} decoys")
    print(f"  flagged {s['flagged']}  false rings {s['false_rings']}  missed {s['missed']}")
    print(f"  window {graph['window_days']} days, threshold {graph['threshold']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
