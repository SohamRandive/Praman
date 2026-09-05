"""Walk real corpus cases through the evidence engine and show what it decides.

    python3 -m praman.demo            # six illustrative cases
    python3 -m praman.demo --code 13.1 --limit 3
    python3 -m praman.demo --no-colour

Reads the generated corpus rather than fixtures, so nothing here is staged: the
cases are whichever real disputes match, and the verdicts are the engine's.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval.metrics import rupees

ROOT = Path(__file__).resolve().parents[1]


class Ink:
    def __init__(self, enabled: bool) -> None:
        self.on = enabled and sys.stdout.isatty()

    def __call__(self, code: str, text: str) -> str:
        codes = {"g": "32", "r": "31", "y": "33", "b": "34", "d": "2", "B": "1"}
        return f"\033[{codes[code]}m{text}\033[0m" if self.on else text


def show(d: dict[str, Any], why: str, ink: Ink) -> None:
    rule = "-" * 76
    badge = (
        ink("g", "SUFFICIENT") if d["evidence_sufficient"] else ink("r", d["routing"].upper())
    )
    print(f"\n{ink('B', rule)}\n{ink('B', why)}\n{ink('B', rule)}")
    print(f"  {d['dispute_id']}   {ink('B', d['reason_code'])} ({d['network']})   "
          f"{rupees(d['amount_minor'])}   {badge}")
    if d["resolved_code"] != d["reason_code"]:
        print(ink("d", f"  resolved {d['reason_code']} -> {d['resolved_code']} "
                       f"at classifier confidence {d['classification_confidence']}"))
    print(f"  {d['merchant_id']}  {ink('d', d['merchant_archetype'])}   "
          f"phase {d['phase']}   split {d['split']}")

    print(f"\n  {ink('B', 'EVIDENCE')}")
    for f in d["required_fields"]:
        mark = ink("g", "[x]") if d["required_present"][f] else ink("r", "[ ]")
        print(f"    {mark} {f:<32} {ink('d', 'required')}")
    for f in d["evidence_fields_present"]:
        if f not in d["required_fields"]:
            print(f"    {ink('b', ' + ')} {f:<32} {ink('d', 'supporting')}")
    print(ink("d", f"    completeness {d['completeness_score']:.2f}   "
                   f"required coverage {d['required_coverage']:.0%}"))

    if d["rejected_artifacts"]:
        print(f"\n  {ink('B', ink('y', 'REJECTED - present but non-qualifying'))}")
        for r in d["rejected_artifacts"]:
            print(f"    {ink('y', '[!]')} {r['api_field']} failed {r['constraint_id']}")
    if d["violated_constraints"]:
        print(f"\n  {ink('B', ink('r', 'BLOCKING CONSTRAINTS VIOLATED'))}")
        for c in d["violated_constraints"]:
            print(f"    {ink('r', '[!]')} {c}")
    if d["warnings"]:
        print(f"    {ink('y', '[~]')} warn (shapes the narrative, does not block): "
              f"{', '.join(d['warnings'])}")

    if d["blocking_gaps"]:
        print(f"\n  {ink('B', ink('r', 'BLOCKED - named, actionable gaps'))}")
        for g in d["blocking_gaps"]:
            print(f"    - {g}")
    else:
        assembled = ink("g", 'Package assembles. action="draft" - never "submit".')
        print(f"\n  {assembled}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--code", help="show cases for one reason code instead")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--no-colour", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.corpus) / "disputes.jsonl"
    if not path.exists():
        print(f"no corpus at {path}. Run `make data` first.", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    ink = Ink(not args.no_colour)

    def first(pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
        return next((d for d in rows if pred(d)), None)

    def rejected_for(d: dict[str, Any], cid: str) -> bool:
        return any(r["constraint_id"] == cid for r in d["rejected_artifacts"])

    if args.code:
        picked = [(d, f"{args.code} case") for d in rows if d["reason_code"] == args.code][:args.limit]
    else:
        picked = [
            (first(lambda d: rejected_for(d, "email_channel_only") and d["reason_code"] == "RZP06"),
             "1. RZP06 - the WhatsApp thread the documentation excludes"),
            (first(lambda d: d["reason_code"] == "13.1" and d["evidence_sufficient"]
                   and len(d["evidence_fields_present"]) >= 3),
             "2. 13.1 - complete package, delivery evidenced before the dispute"),
            (first(lambda d: "delivery_before_dispute" in d["violated_constraints"]),
             "3. Paperwork attached, case lost - the parcel arrived after the dispute"),
            (first(lambda d: d["reason_code"] == "RZP05" and not d["payment_captured"]),
             "4. RZP05 - deterministic branch on capture status, no model involved"),
            (first(lambda d: d["routing"] == "route_to_human" and d["reason_code"] in ("4853", "4854")),
             "5. 4853 - classifier below the confidence floor, routed to a human"),
            (first(lambda d: "legibility_check" in d["violated_constraints"]),
             "6. RuPay 1101 - the code that exists because the last scan was unreadable"),
        ][:args.limit]

    for d, why in picked:
        if d:
            show(d, why, ink)
        else:
            print(f"\n  (no corpus case matched: {why})")

    n = len(rows)
    blocked = sum(1 for d in rows if d["blocking_gaps"])
    human = sum(1 for d in rows if d["routing"] == "route_to_human")
    whatsapp = sum(1 for d in rows if rejected_for(d, "email_channel_only"))
    print(f"\n{ink('B', '-' * 76)}")
    print(f"  across all {n:,} corpus disputes: {blocked:,} blocked ({blocked / n:.1%}), "
          f"{human:,} routed to a human,")
    print(f"  {whatsapp:,} WhatsApp threads refused as non-qualifying evidence")
    print(ink("B", "-" * 76))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
