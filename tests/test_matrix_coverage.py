"""Every reason code in the matrix is exercised.

Two properties are asserted across all 35 codes, because both are the kind of
thing that rots silently as the matrix grows:

  satisfiable   a well-documented merchant can produce a sufficient package for
                every code. A constraint that no artifact can satisfy would
                quietly make a code unwinnable and nobody would notice.
  blocking      a merchant with nothing on file is blocked with a *named* gap
                for every code that requires anything at all.
"""

from __future__ import annotations

import pytest

from praman.evidence import Classification, ReasonCodeMatrix, assemble
from tests.helpers import artifact, context

MATRIX = ReasonCodeMatrix.load()
ALL_CODES = sorted(MATRIX.codes)

# Codes that cannot resolve from the code alone. Each gets the input its
# resolution strategy needs, mirroring what the caller supplies in production.
RESOLUTION_INPUTS: dict[str, dict] = {
    "4853": {"classification": Classification("13.1", 0.9)},
    "4854": {"classification": Classification("13.1", 0.9)},
    "RZP00": {"classification": Classification("RZP01", 0.9)},
    "RZP05": {"payment": {"captured": True}},
}


def full_context(code: str):
    extra = RESOLUTION_INPUTS.get(code, {})
    return context(
        dispute={"cancellation_requested_at": "2026-03-15T09:00:00+05:30"},
        payment=extra.get("payment", {}),
    )


def satisfying(api_field: str):
    """An artifact carrying every field any constraint in the matrix reads.

    Deliberately over-supplied: the point is that a merchant with complete
    records passes, so a constraint that still fails here is a matrix bug.
    """
    common = {"ocr_confidence": 0.95}
    specific = {
        "shipping_proof": {
            "delivered_at": "2026-03-08T14:30:00+05:30",
            "shipped_at": "2026-03-05T09:00:00+05:30",
            "signature_present": True,
        },
        "refund_confirmation": {"amount_minor": 1_840_000},
        "refund_cancellation_policy": {"published_at": "2026-01-01T00:00:00+05:30"},
        "customer_communication": {"channel": "email"},
    }
    return artifact(api_field, **common, **specific.get(api_field, {}))


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_code_is_satisfiable_by_a_well_documented_merchant(code):
    ctx = full_context(code)
    reqs = MATRIX.resolve(code, ctx, RESOLUTION_INPUTS.get(code, {}).get("classification"))
    assert reqs.routing == "assemble", reqs.unresolved_reason
    arts = [satisfying(f) for f in list(reqs.required) + list(reqs.supporting)]
    p = assemble(reqs, arts, ctx, MATRIX.scoring)
    assert p.sufficient, f"{code}: {[g.name for g in p.blocking_gaps]}"
    assert p.completeness_score == 1.0
    assert p.required_coverage == 1.0


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_code_blocks_a_merchant_with_nothing_on_file(code):
    ctx = full_context(code)
    reqs = MATRIX.resolve(code, ctx, RESOLUTION_INPUTS.get(code, {}).get("classification"))
    p = assemble(reqs, [], ctx, MATRIX.scoring)
    if not reqs.required:
        pytest.skip(f"{code} declares no required fields")
    assert not p.sufficient
    assert p.blocking_gaps
    for gap in p.blocking_gaps:
        assert gap.name.strip() and gap.remedy.strip(), f"{code}: unnamed gap"
        assert not gap.name.endswith("_"), f"{code}: gap name is a raw identifier"


@pytest.mark.parametrize("code", ALL_CODES)
def test_action_is_always_draft(code):
    """Hard constraint. There is no code path that sets `submit`."""
    ctx = full_context(code)
    reqs = MATRIX.resolve(code, ctx, RESOLUTION_INPUTS.get(code, {}).get("classification"))
    p = assemble(reqs, [satisfying(f) for f in reqs.required], ctx, MATRIX.scoring)
    assert p.api_payload["action"] == "draft"


# One constraint-violation case per network family, as required by the phase
# exit criteria. Each names the real-world failure it stands for.
VIOLATIONS = [
    pytest.param(
        "13.1", "delivery_before_dispute",
        [artifact("shipping_proof", delivered_at="2026-03-25T10:00:00+05:30")],
        {}, id="visa-delivery-after-dispute",
    ),
    pytest.param(
        "1061", "refund_amount_matches_payment",
        [artifact("refund_confirmation", amount_minor=500_000)],
        {}, id="rupay-partial-refund",
    ),
    pytest.param(
        "C05", "shipped_before_cancellation_request",
        [artifact("shipping_proof", shipped_at="2026-03-20T10:00:00+05:30"),
         artifact("refund_cancellation_policy", published_at="2026-01-01T00:00:00+05:30")],
        {"dispute": {"cancellation_requested_at": "2026-03-15T09:00:00+05:30"}},
        id="amex-shipped-after-cancellation",
    ),
    pytest.param(
        "RZP04", "refund_amount_matches_payment",
        [artifact("refund_confirmation", amount_minor=1_000)],
        {}, id="razorpay-refund-mismatch",
    ),
    pytest.param(
        "4850", None, [], {}, id="mastercard-missing-required",
    ),
]


@pytest.mark.parametrize("code,constraint_id,arts,ctx_kw", VIOLATIONS)
def test_constraint_violation_per_network_family(code, constraint_id, arts, ctx_kw):
    ctx = context(**ctx_kw)
    reqs = MATRIX.resolve(code, ctx)
    p = assemble(reqs, arts, ctx, MATRIX.scoring)
    assert not p.sufficient
    if constraint_id:
        assert constraint_id in p.violated_constraints, p.constraint_outcomes
    else:
        assert any(g.kind == "missing_required_field" for g in p.blocking_gaps)


def test_all_five_network_families_are_covered_by_the_violation_suite():
    covered = {MATRIX.codes[p.values[0]]["network"] for p in VIOLATIONS}
    assert covered == {"visa", "mastercard", "rupay", "amex", "razorpay"}
