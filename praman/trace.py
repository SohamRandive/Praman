"""Trace one case through every stage of the evidence engine, live.

    python3 -m praman.trace              # the RZP06 WhatsApp case
    python3 -m praman.trace --no-colour

The product thesis on one screen: the same merchant, the same facts, one
document swapped - a WhatsApp thread for an email thread - and the opposite
outcome. Nothing here is precomputed; every value printed is what the engine
returns for these inputs.
"""

from __future__ import annotations

import argparse
import json
import sys

from eval.metrics import rupees
from praman.evidence import CaseContext, EvidenceArtifact, ReasonCodeMatrix, assemble
from praman.evidence.engine import _bind, _evaluate_constraints, _score


class Ink:
    CODES = {"g": "32", "r": "31", "y": "33", "d": "2", "B": "1"}

    def __init__(self, enabled: bool) -> None:
        self.on = enabled and sys.stdout.isatty()

    def __call__(self, code: str, text: str) -> str:
        return f"\033[{self.CODES[code]}m{text}\033[0m" if self.on else text


def case() -> tuple[CaseContext, list[EvidenceArtifact]]:
    context = CaseContext(
        dispute={"amount_minor": 1_840_000, "created_at": "2026-03-18T11:00:00+05:30"},
        payment={"amount_minor": 1_840_000, "created_at": "2026-03-01T09:00:00+05:30",
                 "captured": True},
        order={"sla_due_at": "2026-03-10T20:00:00+05:30"},
    )
    artifacts = [
        EvidenceArtifact(
            "doc_Kj4nP2xVqLmR8t", "courier_api", "delivery_confirmation", "shipping_proof",
            "a1f9c3", "2026-03-19T08:14:00+05:30",
            {"delivered_at": "2026-03-12T14:32:00+05:30",
             "shipped_at": "2026-03-04T10:05:00+05:30",
             "signature_present": True, "carrier": "bluedart", "ocr_confidence": 0.94}),
        EvidenceArtifact(
            "doc_Wq8mZ1tYbNc5Ju", "support_desk", "whatsapp_thread", "customer_communication",
            "b7e2d1", "2026-03-19T08:15:00+05:30",
            {"channel": "whatsapp", "last_contact_at": "2026-03-16T19:40:00+05:30",
             "ocr_confidence": 0.91}),
        EvidenceArtifact(
            "doc_Rt3vX9pKdHf6Lm", "merchant_records", "invoice", "billing_proof",
            "c4a8f0", "2026-03-19T08:16:00+05:30",
            {"settled_at": "2026-03-01T09:02:00+05:30", "ocr_confidence": 0.88}),
    ]
    return context, artifacts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="RZP06")
    ap.add_argument("--no-colour", action="store_true")
    args = ap.parse_args(argv)
    ink = Ink(not args.no_colour)

    def stage(n: object, title: str) -> None:
        bar = "=" * 78
        print(f"\n{ink('B', bar)}\n{ink('B', f' STAGE {n}  {title}')}\n{ink('B', bar)}")

    matrix = ReasonCodeMatrix.load()
    context, artifacts = case()

    print(f"{ink('B', 'A dispute arrives.')}  disp_AHfqOvkldwsbqt   "
          f"{ink('B', args.code)} Business Not Responding   "
          f"{rupees(1_840_000)} debited and held")
    print(ink("d", "Three documents are on file. Whether they are the right three"))
    print(ink("d", "is the entire question, and it is not a matter of opinion."))

    stage(1, "RESOLVE  reason code -> requirements (dictionary lookup, no model)")
    reqs = matrix.resolve(args.code, context)
    print(f'  {ink("B", reqs.reason_code)} ({reqs.network})  "{reqs.title}"')
    print(f"  required    {ink('g', str(list(reqs.required)))}")
    print(f"  supporting  {ink('d', str(list(reqs.supporting)))}")
    print(f"  constraints {[c['id'] for c in reqs.constraints]}")

    stage(2, "BIND  artifacts -> contest() fields, enforcing this code's qualifiers")
    bound, rejected = _bind(artifacts, reqs, context)
    for a in artifacts:
        if a in bound.get(a.api_field, []):
            print(f"  {ink('g', 'bound   ')} {a.artifact_id}  {a.api_field:<24}"
                  f" {ink('d', a.artifact_type)}")
    for r in rejected:
        print(f"  {ink('y', 'REJECTED')} {r.artifact_id}  {r.api_field:<24}"
              f" {ink('y', r.constraint_id)}")
        print(f"           {ink('d', r.reason)}")
    print(ink("d", "\n  The thread is not dropped - it is recorded as non-qualifying."))
    print(ink("d", "  Silently uncounting it is how a merchant loses a dispute while"))
    print(ink("d", "  believing the package was complete."))

    stage(3, "SCORE  completeness, required weight 1.0 / supporting 0.3")
    completeness, coverage, missing = _score(bound, reqs, matrix.scoring)
    for f in reqs.required:
        mark = ink("g", "[x]") if bound.get(f) else ink("r", "[ ]")
        print(f"  {mark} {f:<28} required   1.0")
    for f in reqs.supporting:
        mark = ink("g", "[x]") if bound.get(f) else ink("d", "[ ]")
        print(f"  {mark} {f:<28} supporting 0.3")
    print(f"\n  completeness {ink('B', f'{completeness:.3f}')}   "
          f"required coverage {ink('B', f'{coverage:.0%}')}   "
          f"missing {ink('r', str(missing))}")

    stage(4, "CONSTRAINTS  structured predicates, never eval'd strings")
    colours = {"passed": "g", "violated": "r", "unevaluated": "y", "not_applicable": "d"}
    for o in _evaluate_constraints(reqs, bound, context, frozenset(missing)):
        status = ink(colours[o.status], f"{o.status.upper():<15}")
        print(f"  {status} {o.constraint_id}  {ink('d', '(' + o.severity + ')')}")
        print(f"                  {ink('d', o.detail)}")

    stage(5, "ASSEMBLE  verdict, and gaps a human can act on")
    pkg = assemble(reqs, artifacts, context, matrix.scoring)
    verdict = ink("g", "True") if pkg.sufficient else ink("r", "False")
    print(f"  sufficient {verdict}   routing {ink('B', pkg.routing)}")
    for g in pkg.blocking_gaps:
        print(f"\n  {ink('r', 'BLOCKING')} {g.name}")
        print(f"           {ink('d', '-> ' + g.remedy)}")
    for w in pkg.warnings:
        print(f"\n  {ink('y', 'WARN    ')} {w.name}")

    stage(6, "PAYLOAD  the contest() request body, verbatim")
    print(json.dumps(pkg.api_payload, indent=2))
    print(f'\n  {ink("B", "action is hard-coded to draft.")} No code path in this repository')
    print("  sets it to submit. A human approval does that, and writes its own")
    print("  audit record when it does.")

    stage("*", "THE SAME CASE, with an email thread instead of WhatsApp")
    swapped = [
        EvidenceArtifact(
            "doc_Nm5kT7wQrBv2Xz", "support_desk", "email_thread", "customer_communication",
            "d9b3e5", "2026-03-19T08:15:00+05:30",
            {"channel": "email", "last_contact_at": "2026-03-16T19:40:00+05:30",
             "ocr_confidence": 0.91})
        if a.api_field == "customer_communication" else a
        for a in artifacts
    ]
    after = assemble(reqs, swapped, context, matrix.scoring)
    verdict = ink("g", "True") if after.sufficient else ink("r", "False")
    print(f"  sufficient {verdict}   completeness {after.completeness_score:.3f}"
          f"   routing {ink('B', after.routing)}")
    print(ink("d", "\n  One document swapped. Same merchant, same facts, opposite outcome."))
    print(ink("d", "  That is the loss this product exists to prevent, and the reason"))
    print(ink("d", "  binding rejects loudly instead of quietly not counting."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
