"""Draft representments over real corpus cases and show the verifier working.

    python3 -m praman.drafting --corpus data/corpus

Two passes, and the difference between them is the point.

The first drafts with the templated provider, which is grounded by construction:
every sentence is assembled from the field values it cites, nothing is stripped,
and every draft is emitted. That is the system's normal behaviour and it is
boring, which is correct.

The second re-drafts the same cases through the fault-injecting provider, which
emits the failure modes a generative drafter exhibits. Every fabrication is
caught and the affected drafts are blocked rather than filed.

**Read the second pass for what it is.** It is fault injection against our own
verifier. It is not a measurement of any model's hallucination rate, and this
repository does not claim one - no hosted model is wired up, so no such rate has
been observed. The claim being made is that this class of error is caught.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from praman.drafting import (
    FaultInjectingProvider,
    TemplatedProvider,
    contest_payload,
    draft_representment,
    synthesize,
)

ROOT = Path(__file__).resolve().parents[2]


def load(corpus: Path, limit: int) -> list[dict[str, Any]]:
    with open(corpus / "disputes.jsonl", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    # Only cases that would actually be drafted: a package that assembles, on
    # the held-out split. Drafting a blocked package is not a thing the system
    # does, so measuring it here would measure nothing.
    usable = [
        r for r in rows
        if r["split"] == "test" and r["evidence_sufficient"] and r["evidence_fields_present"]
    ]
    return usable[:limit]


def artifacts_for(row: dict[str, Any]):
    return synthesize(
        row["dispute_id"], row["evidence_fields_present"],
        created_at=row["created_at"],
        payment_created_at=row["payment_created_at"],
        amount_minor=row["amount_minor"],
        channel=row.get("comms_channel", "email"),
    )


def run(rows: list[dict[str, Any]], provider) -> dict[str, Any]:
    drafted = blocked = stripped = 0
    log: list[str] = []
    for row in rows:
        arts = artifacts_for(row)
        result = draft_representment(
            arts, tuple(row["required_fields"]), {"dispute_id": row["dispute_id"]},
            provider=provider,
        )
        stripped += len(result.stripped)
        blocked += int(result.blocked)
        drafted += int(not result.blocked)
        for strip in result.stripped:
            log.append(
                f"  {row['dispute_id']}  {row['reason_code']:<6} STRIP {strip.reason}\n"
                f"      sentence: {strip.text}\n"
                f"      why:      {strip.detail}"
            )
        if result.blocked:
            log.append(f"      -> BLOCKED: {result.block_reason}")
    return {"drafted": drafted, "blocked": blocked, "stripped": stripped, "log": log}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--show", type=int, default=6, help="strip events to print")
    args = ap.parse_args(argv)

    rows = load(Path(args.corpus), args.limit)
    if not rows:
        print("no drafted-eligible cases in the corpus; run `make data`")
        return 1

    print(f"{len(rows)} test-split cases with an assemblable package\n")

    print("1. Templated provider - grounded by construction")
    print("-" * 52)
    clean = run(rows, TemplatedProvider())
    print(f"  drafted {clean['drafted']}   blocked {clean['blocked']}   "
          f"claims stripped {clean['stripped']}")
    print("  Nothing is stripped because no sentence can carry a value that did")
    print("  not come out of a cited field. The verifier still runs over it: a")
    print("  check that only runs against inputs you already trust is not a check.")

    sample = rows[0]
    arts = artifacts_for(sample)
    result = draft_representment(
        arts, tuple(sample["required_fields"]), {"dispute_id": sample["dispute_id"]})
    print(f"\n  sample draft, {sample['dispute_id']} ({sample['reason_code']}):")
    print(f"    {result.summary[:300]}")
    body = contest_payload({}, result, sample["amount_minor"])
    print(f"    action={body['action']!r}  coverage={result.coverage_after}  "
          f"groundedness={result.groundedness}")

    print("\n\n2. Fault-injecting provider - the verifier under load")
    print("-" * 52)
    print("  Fault injection against our own verifier. NOT a measurement of any")
    print("  model's error rate; none has been observed, because no hosted model")
    print("  is wired up. The claim is that this class of error is caught.\n")
    faulty = run(rows, FaultInjectingProvider(rate=0.35))
    print(f"  drafted {faulty['drafted']}   blocked {faulty['blocked']}   "
          f"claims stripped {faulty['stripped']}")
    print(f"\n  {min(args.show, len(faulty['log']))} of {len(faulty['log'])} strip events:\n")
    for line in faulty["log"][:args.show]:
        print(line)

    kinds: dict[str, int] = {}
    for line in faulty["log"]:
        if " STRIP " in line:
            kinds[line.split(" STRIP ")[1].strip()] = 1 + kinds.get(
                line.split(" STRIP ")[1].strip(), 0)
    print("\n  strips by kind:")
    for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"    {kind:<22}{n:>5}")
    print("\n  `unsupported_value` is the one that matters. Those sentences carried")
    print("  citations that RESOLVED, against artifacts that were genuinely in the")
    print("  package, with a fabricated date in the prose beside them - so a")
    print("  verifier that only checked that citations resolve would have passed")
    print("  them straight to an issuer. Scanning the prose against the cited")
    print("  values is what catches them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
