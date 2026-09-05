"""Evidence engine tests, in the order the codes were chosen for.

RZP06 first because email_channel_only is the most testable rule in the matrix
and the most India-specific insight in the design; then RZP05 for the
zero-model deterministic branch; 1101 for the OCR gate; 13.1 as the canonical
high-volume case; 4853 as the one place a classifier earns its keep; M01 last,
because it must be able to resolve to *accept*.
"""

from __future__ import annotations

import pytest

from praman.evidence import Classification, assemble
from tests.helpers import artifact, context

DELIVERED = "2026-03-12T14:30:00+05:30"


def pkg(matrix, code, artifacts, ctx=None, classification=None):
    reqs = matrix.resolve(code, ctx or context(), classification)
    return assemble(reqs, artifacts, ctx or context(), matrix.scoring)


# ------------------------------------------------------------------- RZP06 --


def test_rzp06_whatsapp_thread_is_non_qualifying(matrix):
    """The documentation excludes WhatsApp. A large share of Indian SMB support
    lives there, so this is a real and silent way merchants lose with paperwork
    attached. It must never be counted toward completeness."""
    p = pkg(
        matrix,
        "RZP06",
        [
            artifact("shipping_proof", delivered_at=DELIVERED, signature_present=True),
            artifact("billing_proof"),
            artifact("customer_communication", channel="whatsapp"),
        ],
    )
    assert not p.sufficient
    assert p.routing == "blocked"
    assert [r.constraint_id for r in p.rejected] == ["email_channel_only"]
    assert "customer_communication" not in p.bound
    gap = next(g for g in p.blocking_gaps if g.api_field == "customer_communication")
    assert gap.kind == "non_qualifying_artifact"
    # The WhatsApp document must not appear in the submitted payload at all.
    assert "customer_communication" not in p.api_payload


def test_rzp06_email_thread_qualifies(matrix):
    p = pkg(
        matrix,
        "RZP06",
        [
            artifact("shipping_proof", delivered_at="2026-03-08T14:30:00+05:30",
                     signature_present=True),
            artifact("billing_proof"),
            artifact("customer_communication", channel="email"),
        ],
    )
    assert p.sufficient, p.blocking_gaps
    assert p.required_coverage == 1.0
    assert p.api_payload["customer_communication"] == ["doc_customer_communication"]


def test_rzp06_late_delivery_warns_but_does_not_block(matrix):
    """delivered_within_committed_sla is a warning: it shapes the narrative,
    it does not disqualify the package."""
    p = pkg(
        matrix,
        "RZP06",
        [
            artifact("shipping_proof", delivered_at=DELIVERED, signature_present=True),
            artifact("billing_proof"),
            artifact("customer_communication", channel="email"),
        ],
    )
    assert p.sufficient
    assert [w.constraint_id for w in p.warnings] == ["delivered_within_committed_sla"]


# ------------------------------------------------------------------- RZP05 --


@pytest.mark.parametrize(
    "captured,expected_required,argument",
    [(True, "billing_proof", "service_delivered"),
     (False, "access_activity_log", "funds_not_received")],
)
def test_rzp05_branches_on_capture_status(matrix, captured, expected_required, argument):
    """Forks on a fact already present on the payment object. No model involved."""
    reqs = matrix.resolve("RZP05", context(payment={"captured": captured}))
    assert reqs.required == (expected_required,)
    assert argument in reqs.resolution_note


def test_rzp05_unknown_capture_status_routes_to_human(matrix):
    """Which argument to make depends on the fact. Absent it, route - never guess."""
    reqs = matrix.resolve("RZP05", context())
    assert reqs.routing == "route_to_human"
    p = assemble(reqs, [artifact("billing_proof")], context(), matrix.scoring)
    assert p.routing == "route_to_human"
    assert any(g.kind == "unresolved_code" for g in p.blocking_gaps)


# -------------------------------------------------------------------- 1101 --


def test_1101_blocks_an_illegible_scan(matrix):
    """1101 exists *because* the previous submission was unreadable.
    Resubmitting the same scan loses again."""
    p = pkg(
        matrix,
        "1101",
        [artifact("shipping_proof", delivered_at=DELIVERED, ocr_confidence=0.62)],
    )
    assert not p.sufficient
    assert "legibility_check" in p.violated_constraints
    assert p.routing == "blocked"


def test_1101_passes_a_legible_scan(matrix):
    p = pkg(
        matrix,
        "1101",
        [artifact("shipping_proof", delivered_at=DELIVERED, ocr_confidence=0.94)],
    )
    assert p.sufficient, p.blocking_gaps


def test_1101_unknown_ocr_confidence_is_unevaluated_not_passed(matrix):
    """ADR-008: declared unknown, never assumed to pass."""
    p = pkg(matrix, "1101", [artifact("shipping_proof", delivered_at=DELIVERED)])
    assert "legibility_check" in p.unevaluated_constraints
    assert not p.sufficient
    assert p.routing == "route_to_human"


# -------------------------------------------------------------------- 13.1 --


def test_131_complete_package_is_sufficient(matrix):
    p = pkg(
        matrix,
        "13.1",
        [
            artifact("shipping_proof", delivered_at=DELIVERED, signature_present=True),
            artifact("proof_of_service"),
            artifact("access_activity_log"),
            artifact("customer_communication", channel="email"),
        ],
    )
    assert p.sufficient
    assert p.completeness_score == 1.0
    assert p.api_payload["action"] == "draft"


def test_131_missing_delivery_proof_emits_a_named_actionable_gap(matrix):
    p = pkg(matrix, "13.1", [artifact("customer_communication", channel="email")])
    assert not p.sufficient
    gap = p.blocking_gaps[0]
    assert gap.name == "No proof of delivery."
    assert "courier" in gap.remedy
    assert gap.api_field == "shipping_proof"


def test_131_delivery_after_dispute_is_a_blocking_violation(matrix):
    """Paperwork attached, case lost: the parcel arrived after the cardholder
    had already raised the dispute."""
    p = pkg(
        matrix,
        "13.1",
        [artifact("shipping_proof", delivered_at="2026-03-25T10:00:00+05:30",
                  signature_present=True)],
    )
    assert not p.sufficient
    assert "delivery_before_dispute" in p.violated_constraints


def test_131_unsigned_delivery_warns_only(matrix):
    p = pkg(matrix, "13.1", [artifact("shipping_proof", delivered_at=DELIVERED,
                                      signature_present=False)])
    assert p.sufficient
    assert [w.constraint_id for w in p.warnings] == ["signature_strongly_preferred"]


def test_131_partial_support_scores_between_zero_and_one(matrix):
    p = pkg(matrix, "13.1", [artifact("shipping_proof", delivered_at=DELIVERED,
                                      signature_present=True)])
    # 1 required (1.0) of 1.0 + 0 of 3 supporting (0.9) => 1.0 / 1.9
    assert p.completeness_score == pytest.approx(1.0 / 1.9, abs=1e-6)
    assert p.required_coverage == 1.0


# -------------------------------------------------------------------- 4853 --


def test_4853_without_a_classification_routes_to_human(matrix):
    reqs = matrix.resolve("4853")
    assert reqs.routing == "route_to_human"


def test_4853_low_confidence_routes_to_human(matrix):
    reqs = matrix.resolve("4853", context(), Classification("13.1", 0.41))
    assert reqs.routing == "route_to_human"
    assert "below the 0.70 floor" in reqs.unresolved_reason


def test_4853_confident_classification_delegates_to_the_sibling_code(matrix):
    reqs = matrix.resolve("4853", context(), Classification("13.6", 0.88))
    assert reqs.resolved_code == "13.6"
    assert reqs.required == ("refund_confirmation",)
    assert "delegated 4853 -> 13.6" in reqs.resolution_note


def test_4853_rejects_a_code_outside_its_candidate_set(matrix):
    reqs = matrix.resolve("4853", context(), Classification("M49", 0.99))
    assert reqs.routing == "route_to_human"
    assert "not a candidate" in reqs.unresolved_reason


def test_rzp00_delegation_keeps_the_parent_channel_constraint(matrix):
    """RZP00 delegates the sub-claim but its own email_channel_only still governs."""
    reqs = matrix.resolve("RZP00", context(), Classification("RZP01", 0.90))
    assert reqs.resolved_code == "RZP01"
    assert "email_channel_only" in {c["id"] for c in reqs.constraints}
    p = assemble(
        reqs,
        [artifact("shipping_proof", delivered_at=DELIVERED),
         artifact("customer_communication", channel="whatsapp")],
        context(),
        matrix.scoring,
    )
    assert [r.constraint_id for r in p.rejected] == ["email_channel_only"]


# --------------------------------------------------------------------- M01 --


def test_m01_is_satisfiable_and_carries_no_contest_bias(matrix):
    """M01 is rarely winnable. The engine's job is to report the package
    honestly; it must not manufacture sufficiency, and it must not refuse a
    genuinely complete one either."""
    complete = pkg(matrix, "M01", [artifact("explanation_letter"),
                                   artifact("customer_communication", channel="email")])
    assert complete.sufficient
    empty = pkg(matrix, "M01", [])
    assert not empty.sufficient
    assert empty.blocking_gaps[0].name == "No explanation letter."


def test_every_gap_remedy_is_an_instruction_not_a_predicate_detail(matrix):
    """A merchant reading a blocked package must get something they can act on.
    The predicate detail that produced the gap belongs in the audit trail, not
    in the instruction."""
    p = pkg(
        matrix,
        "RZP06",
        [
            artifact("billing_proof"),
            artifact("customer_communication", channel="whatsapp"),
        ],
    )
    gap = next(g for g in p.blocking_gaps if g.constraint_id == "email_channel_only")
    assert "Supply the email thread" in gap.remedy
    assert "artifact.channel" not in gap.remedy
    # The technical detail is still recorded, just not shown as the remedy.
    assert "whatsapp" in p.rejected[0].reason


def test_trace_runs_and_shows_the_one_document_swap(capsys):
    """The trace is the product thesis on one screen and it is demoed live, so
    it is tested like anything else that can break in front of an audience."""
    from praman.trace import main

    assert main(["--no-colour"]) == 0
    out = capsys.readouterr().out
    assert "REJECTED" in out and "email_channel_only" in out
    assert '"action": "draft"' in out
    assert "Supply the email thread" in out
    before, after = out.split("THE SAME CASE")
    assert "sufficient False" in before
    assert "sufficient True" in after
