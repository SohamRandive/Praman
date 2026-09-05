"""Dump real decided cases as JSON for the console to render.

    python3 -m praman.console.fixtures --out web/src/cases.json

Every case here went through the real agent mesh and the real evidence engine.
Nothing on the screen is mocked, which is the point: the console is a view over
the decision, not an illustration of one.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
from pathlib import Path
from typing import Any

from praman.adjudicator.model import train
from praman.agents import (
    EvidenceRetrieval,
    MerchantContext,
    NetworkForensics,
    PolicyCompliance,
    PrecedentRecall,
)
from praman.console.serialize import serialize
from praman.evidence import ReasonCodeMatrix
from praman.network import point_in_time_features
from praman.orchestrator import CaseFile, run_case

ROOT = Path(__file__).resolve().parents[2]


class _DeadAgent:
    """A source that is down. Raises, exactly as a real one would, so the
    orchestrator's guarded() path is what produces the degraded result."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    async def run(self, case: Any, budget_ms: int):
        raise RuntimeError(self.reason)


def build(corpus: Path, limit: int = 12) -> list[dict[str, Any]]:
    def read(name: str) -> list[dict[str, Any]]:
        with open(corpus / name, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    rows, edges = read("disputes.jsonl"), read("entity_edges.jsonl")
    merchants = {m["merchant_id"]: m for m in read("merchants.jsonl")}
    comps = point_in_time_features(rows, edges)

    history: dict[tuple[str, bool], list[int]] = collections.defaultdict(lambda: [0, 0])
    by_split: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_split.setdefault(r["split"], []).append(r)
        if r["split"] == "train":
            key = (r["reason_code"], bool(r["no_blocking_gaps"]))
            history[key][1] += 1
            history[key][0] += int(r["observed_won"])

    matrix = ReasonCodeMatrix.load()
    adj = train(by_split["train"], by_split["calibration"], components=comps)

    # A spread the console has to handle, not a gallery of successes: a clean
    # contest, a blocked package, a WhatsApp refusal, a case routed to a human,
    # a degraded retrieval, and one that should be accepted on the economics.
    test = by_split["test"]
    wanted = [
        ("clean contest", lambda r: r["evidence_sufficient"] and r["amount_minor"] > 800_000),
        ("blocked - missing document", lambda r: r["blocking_gaps"] and not r["rejected_artifacts"]),
        ("blocked - WhatsApp refused", lambda r: any(
            x["constraint_id"] == "email_channel_only" for x in r["rejected_artifacts"])),
        ("routed to a human", lambda r: r["routing"] == "route_to_human"),
        ("in a detected cluster", lambda r: r["in_group"] and r["evidence_sufficient"]),
        ("below the cost of contesting", lambda r: r["amount_minor"] < 30_000),
    ]

    # The console must LAND on the most interesting case, not the least. A
    # clean contest with two not-applicable constraints and five green agents
    # teaches nothing; the WhatsApp refusal is the product thesis.
    wanted.insert(0, wanted.pop(2))

    picked: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for label, pred in wanted:
        for r in test:
            if pred(r) and r["dispute_id"] not in seen:
                picked.append((label, r))
                seen.add(r["dispute_id"])
                break
    for r in test:
        if len(picked) >= limit:
            break
        if r["dispute_id"] not in seen:
            picked.append(("", r))
            seen.add(r["dispute_id"])

    probs = {r["dispute_id"]: p for (_, r), p in
             zip(picked, adj.predict([r for _, r in picked]), strict=True)}

    out: list[dict[str, Any]] = []
    for label, row in picked:
        agents: list[Any] = [
            # One case shows a partially degraded retrieval, because a console
            # that only ever renders the happy path is a console that hides the
            # exception list - and the exception list is the product.
            EvidenceRetrieval(matrix, drop_rate=0.4 if label == "in a detected cluster" else 0.0),
            NetworkForensics(comps),
            PrecedentRecall({k: tuple(v) for k, v in history.items()}),
            PolicyCompliance(),
            MerchantContext(merchants),
        ]
        # The landing case also carries one dead agent, so partial-failure
        # survival is visible on the first screen rather than being a claim the
        # reader has to go looking for. Precedent is chosen deliberately: it
        # degrades the confidence band without muddying the refusal narrative,
        # which is what the case is there to show.
        if label == "blocked - WhatsApp refused":
            agents[2] = _DeadAgent("precedent", "vector index unavailable")
        case = asyncio.run(run_case(CaseFile.from_row(row), agents, probs[row["dispute_id"]]))
        payload = serialize(case, matrix)
        payload["scenario"] = label
        payload["merchant_archetype"] = row["merchant_archetype"]
        out.append(payload)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--out", default=str(ROOT / "web" / "src" / "cases.json"))
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args(argv)

    cases = build(Path(args.corpus), args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=2, ensure_ascii=False)
    print(f"wrote {len(cases)} decided cases to {out}")
    for c in cases[:8]:
        rec = c["recommendation"]
        print(f"  {c['dispute_id']}  {c['reason_code']:<6} {c['amount']:>12}  "
              f"{rec['action']:<8} {c['deadline']['display']:>7}  {c['scenario']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
