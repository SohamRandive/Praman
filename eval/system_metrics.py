"""System-level metrics: latency, degradation, model calls, cost.

    python3 -m eval.system_metrics --corpus data/corpus

These are the numbers that say whether the thing runs, as distinct from whether
it decides well. A system that recovers Rs 94 lakh in a notebook and takes
forty seconds a case has not recovered anything.

**On cost.** No hosted model is wired up, so no rupee figure is quoted for it.
What is reported is the *call count* - structural, measured, and the only half
of the cost equation this repository actually knows. Multiplying it by a price
nobody has paid would be an invented number, and inventing one here would be
exactly the failure this file exists to measure the absence of.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
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
from praman.evidence import ReasonCodeMatrix
from praman.network import point_in_time_features
from praman.orchestrator import CaseFile, run_case

ROOT = Path(__file__).resolve().parents[1]

#: §15's target. Stated here so a regression fails loudly rather than drifting.
P95_TARGET_S = 6.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def measure(rows: list[dict[str, Any]], comps, matrix, adj, history, merchants,
            drop_rate: float = 0.0) -> dict[str, Any]:
    """Run real cases through the real mesh and time them.

    Wall-clock, in-process, on one machine. That is a floor on a real
    deployment's latency, not a prediction of it: there is no network between
    these agents, and the retrieval they do is stubbed. Reported as what it is.
    """
    probs = adj.predict(rows)
    per_case_s: list[float] = []
    per_agent_ms: dict[str, list[float]] = {}
    statuses: dict[str, dict[str, int]] = {}
    model_calls = 0
    drafted = blocked = stripped = 0

    for row, p in zip(rows, probs, strict=True):
        agents = [
            EvidenceRetrieval(matrix, drop_rate=drop_rate),
            NetworkForensics(comps),
            PrecedentRecall(history),
            PolicyCompliance(),
            MerchantContext(merchants),
        ]
        started = time.perf_counter()
        case = asyncio.run(run_case(CaseFile.from_row(row), agents, float(p)))
        per_case_s.append(time.perf_counter() - started)

        for name, result in case.agent_results.items():
            per_agent_ms.setdefault(name, []).append(result.latency_ms)
            bucket = statuses.setdefault(name, {})
            bucket[result.status] = bucket.get(result.status, 0) + 1

        # One drafting call per contested dispute, and none at all for an
        # accepted one. The model is not on the path of a decision it did not
        # make, which is the architecture and is therefore also the cost model.
        if case.draft is not None:
            model_calls += 1
            drafted += int(not case.draft.blocked)
            blocked += int(case.draft.blocked)
            stripped += len(case.draft.stripped)

    return {
        "cases": len(rows),
        "p50_decision_s": round(percentile(per_case_s, 0.50), 4),
        "p95_decision_s": round(percentile(per_case_s, 0.95), 4),
        "max_decision_s": round(max(per_case_s), 4) if per_case_s else 0.0,
        "mean_decision_s": round(statistics.fmean(per_case_s), 4) if per_case_s else 0.0,
        "agents": {
            name: {
                "p50_ms": round(percentile(lat, 0.50), 2),
                "p95_ms": round(percentile(lat, 0.95), 2),
                "ok": statuses[name].get("ok", 0),
                "degraded": statuses[name].get("degraded", 0),
                "failed": statuses[name].get("failed", 0) + statuses[name].get("timeout", 0),
                "degradation_rate": round(
                    1 - statuses[name].get("ok", 0) / max(len(lat), 1), 4),
            }
            for name, lat in sorted(per_agent_ms.items())
        },
        "model_calls": model_calls,
        "model_calls_per_case": round(model_calls / max(len(rows), 1), 4),
        "model_calls_per_100_disputes": round(100 * model_calls / max(len(rows), 1), 1),
        "drafts_emitted": drafted,
        "drafts_blocked": blocked,
        "claims_stripped": stripped,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--metrics-out", default="web/src/metrics.json")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus)
    with open(corpus / "disputes.jsonl", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    with open(corpus / "entity_edges.jsonl", encoding="utf-8") as fh:
        edges = [json.loads(line) for line in fh]
    with open(corpus / "merchants.jsonl", encoding="utf-8") as fh:
        merchants = {m["merchant_id"]: m for m in (json.loads(x) for x in fh)}

    comps = point_in_time_features(rows, edges)
    by_split: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_split.setdefault(r["split"], []).append(r)

    history: dict[tuple[str, bool], list[int]] = {}
    for r in by_split["train"]:
        key = (r["reason_code"], bool(r["no_blocking_gaps"]))
        won, total = history.get(key, (0, 0))
        history[key] = (won + int(r["observed_won"]), total + 1)

    matrix = ReasonCodeMatrix.load()
    adj = train(by_split["train"], by_split["calibration"], components=comps)
    sample = by_split["test"][:args.n]

    print(f"{len(sample)} test-split cases through the real mesh\n")

    clean = measure(sample, comps, matrix, adj, history, merchants)
    print("1. Time to decision (in-process, one machine)")
    print("-" * 52)
    print(f"  p50 {clean['p50_decision_s'] * 1000:.1f}ms   "
          f"p95 {clean['p95_decision_s'] * 1000:.1f}ms   "
          f"max {clean['max_decision_s'] * 1000:.1f}ms")
    verdict = "PASS" if clean["p95_decision_s"] < P95_TARGET_S else "FAIL"
    print(f"  {verdict} p95 under the {P95_TARGET_S:.0f}s target (SPEC section 15)")
    print("\n  Read this as a FLOOR, not a prediction. There is no network between")
    print("  these agents and their retrieval is stubbed, so a real deployment is")
    print("  strictly slower. What it does establish is that nothing here is")
    print("  accidentally quadratic, and that the deadline budget has room to work.")

    print("\n\n2. Per-agent latency and degradation")
    print("-" * 52)
    print(f"  {'agent':<12}{'p50 ms':>9}{'p95 ms':>9}{'ok':>7}{'degraded':>10}"
          f"{'failed':>8}{'degr rate':>11}")
    for name, a in clean["agents"].items():
        print(f"  {name:<12}{a['p50_ms']:>9.3f}{a['p95_ms']:>9.3f}{a['ok']:>7}"
              f"{a['degraded']:>10}{a['failed']:>8}{a['degradation_rate']:>11.3f}")

    print("\n\n3. Degradation under partial retrieval (drop_rate 0.30)")
    print("-" * 52)
    degraded = measure(sample[:100], comps, matrix, adj, history, merchants, drop_rate=0.30)
    ev = degraded["agents"]["evidence"]
    print(f"  evidence: {ev['ok']} ok, {ev['degraded']} degraded "
          f"({ev['degradation_rate']:.1%} degradation rate)")
    print(f"  every one of those {degraded['cases']} cases still reached a decision")
    print("  Partial failure is the default path, not an error path.")

    print("\n\n4. Model calls and cost")
    print("-" * 52)
    print(f"  drafting calls        {clean['model_calls']:>6} over {clean['cases']} cases")
    print(f"  per case              {clean['model_calls_per_case']:>6.3f}")
    print(f"  per 100 disputes      {clean['model_calls_per_100_disputes']:>6.1f}")
    print(f"  drafts emitted        {clean['drafts_emitted']:>6}")
    print(f"  drafts blocked        {clean['drafts_blocked']:>6}   by the grounding verifier")
    print(f"  claims stripped       {clean['claims_stripped']:>6}")
    share = clean["model_calls_per_case"]
    print("\n  One call per CONTESTED dispute and none for an accepted one, because")
    print("  the model is not on the path of a decision it did not make. That is")
    print("  the architecture, so it is also the cost model: the expected-cost rule")
    print(f"  declining {1 - share:.0%} of this sample is {1 - share:.0%} of the")
    print("  model spend that never happens.")
    print("\n  NO RUPEE COST IS QUOTED. No hosted model is wired up, so the price")
    print("  side of that multiplication is a number this repository does not have.")
    print("  Call count is the half it can measure, and it is the half reported.")

    out = Path(args.metrics_out)
    if out.exists():
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["system"] = {
            **clean,
            "p95_target_s": P95_TARGET_S,
            "measurement": "in-process, single machine, stubbed retrieval - a floor",
            "cost_note": "no hosted model wired; call count reported, no price quoted",
        }
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"\nsystem metrics merged into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
