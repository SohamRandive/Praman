"""The grounding verifier is the only thing between a generated sentence and a
bank. It is tested as such.

Two failure directions matter equally and are tested separately. Letting a
fabricated sentence through is the obvious one. Stripping a TRUE sentence
because a date was formatted differently is the one that gets a verifier
switched off in week two, and it is tested just as hard.
"""

from __future__ import annotations

import pytest

from praman.drafting import (
    SUMMARY_LIMIT,
    Citation,
    Claim,
    FaultInjectingProvider,
    TemplatedProvider,
    assemble_summary,
    checkable_values,
    contest_payload,
    draft_representment,
    synthesize,
    verify_claim,
)
from praman.evidence.types import EvidenceArtifact


def artifact(artifact_id: str = "art_ship", api_field: str = "shipping_proof", **fields):
    return EvidenceArtifact(
        artifact_id=artifact_id,
        source_system="merchant_records",
        artifact_type=api_field,
        api_field=api_field,
        content_hash="0" * 32,
        retrieved_at="2026-03-20T00:00:00+05:30",
        fields=dict(fields),
    )


def claim(text: str, *refs: str, asserts=None, api_field="shipping_proof", required=True):
    return Claim(
        claim_id="clm_1",
        text=text,
        citations=tuple(Citation.parse(r) for r in refs),
        asserts=asserts or {},
        api_field=api_field,
        required=required,
    )


# ------------------------------------------------------- what must be stripped


def test_a_sentence_citing_nothing_is_malformed_not_merely_weak():
    """An empty citation list is a schema violation. There is no reading of the
    architecture in which an uncited sentence reaches an issuer."""
    strip = verify_claim(claim("The cardholder confirmed receipt."), {})
    assert strip is not None
    assert strip.reason == "no_citation"


def test_a_citation_to_an_artifact_not_in_the_package_is_stripped():
    """The shape of a drafter recalling a document from a different case."""
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    strip = verify_claim(
        claim("Delivered on 2026-03-12.", "art_elsewhere.delivered_at"), arts)
    assert strip is not None and strip.reason == "unresolved_artifact"


def test_a_citation_to_a_field_the_artifact_does_not_carry_is_stripped():
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    strip = verify_claim(claim("Signed by the cardholder.", "art_ship.signed_by"), arts)
    assert strip is not None and strip.reason == "unresolved_field"


def test_an_asserted_value_that_contradicts_the_artifact_is_stripped():
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    strip = verify_claim(
        claim("Delivered on 2026-03-12.", "art_ship.delivered_at",
              asserts={"art_ship.delivered_at": "2026-03-19"}),
        arts,
    )
    assert strip is not None and strip.reason == "value_mismatch"


def test_a_fabricated_date_in_the_prose_is_caught_even_with_valid_citations():
    """THE test. This is the failure the whole module exists for.

    The citation resolves, the artifact is real, and `asserts` is internally
    consistent - because the generator never noticed it invented anything. Only
    scanning the prose against the cited values catches it. Without this check
    the sentence goes to an issuer with a real document attached and a date that
    is not in it.
    """
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    strip = verify_claim(
        claim("The consignment was delivered on 2026-03-19.", "art_ship.delivered_at",
              asserts={"art_ship.delivered_at": "2026-03-12"}),
        arts,
    )
    assert strip is not None
    assert strip.reason == "unsupported_value"
    assert "2026-03-19" in strip.detail


def test_a_fabricated_tracking_reference_is_caught():
    arts = {"art_ship": artifact(tracking_id="BLU917986433")}
    strip = verify_claim(
        claim("Shipped under tracking DEL443320917.", "art_ship.tracking_id"), arts)
    assert strip is not None and strip.reason == "unsupported_value"


# ------------------------------------------- what must NOT be stripped
# A verifier that strips true sentences gets switched off, and then nothing is
# checked at all. These are the false-positive guards.


def test_the_same_date_written_differently_is_the_same_date():
    """`12 March 2026` and `2026-03-12` are one assertion to a reader and to an
    issuer. A verifier that failed them apart would strip true sentences."""
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    assert verify_claim(
        claim("The consignment was delivered on 12 March 2026.",
              "art_ship.delivered_at"), arts) is None


def test_currency_formatting_does_not_make_a_true_claim_ungrounded():
    """Rs 18,400 / ₹18400 / INR 18,400 are the same amount."""
    arts = {"art_bill": artifact("art_bill", "billing_proof", amount="Rs 18,400")}
    for written in ("₹18,400", "Rs 18400", "INR 18,400", "Rs. 18,400"):
        assert verify_claim(
            claim(f"The transaction of {written} was authorised.", "art_bill.amount",
                  api_field="billing_proof"),
            arts,
        ) is None, written


def test_prose_carrying_no_checkable_value_passes_on_its_citations_alone():
    """"The consignment was signed for" has nothing an issuer can check against a
    field. It is verified by resolving its citation, not by pattern matching."""
    arts = {"art_ship": artifact(signed_by="the cardholder")}
    assert verify_claim(
        claim("The consignment was signed for on arrival.", "art_ship.signed_by"),
        arts) is None


def test_checkable_values_finds_the_atoms_an_issuer_would_check():
    found = dict(map(reversed, checkable_values(
        "Delivered 2026-03-12 for Rs 18,400 under BLU917986433.")))
    assert found["2026-03-12"] == "date_iso"
    assert found["BLU917986433"] == "reference"
    assert any(k == "amount" for k in found.values())


# ------------------------------------------------------------------ blocking


def test_stripping_a_required_sentence_blocks_the_draft_rather_than_shortening_it():
    """Hard rule 4. If grounding removes the only sentence supporting a required
    document, the draft is blocked and escalated. Emitting the remainder would
    read complete while asserting less than the package promised."""
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}

    class Fabricator:
        name = "test"

        def draft(self, artifacts, required, case):
            return [claim("Delivered on 2026-09-09.", "art_ship.delivered_at")]

    result = draft_representment(arts, ("shipping_proof",), {"dispute_id": "d1"},
                                 provider=Fabricator())
    assert result.blocked
    assert result.summary == ""
    assert result.coverage_before == 1.0 and result.coverage_after == 0.0
    assert "proof of delivery" in result.block_reason
    assert len(result.stripped) == 1


def test_losing_only_a_supporting_sentence_does_not_block():
    """Coverage is measured over REQUIRED fields. Losing supporting colour
    weakens a narrative; losing the delivery proof removes the case."""
    arts = {
        "art_ship": artifact(delivered_at="2026-03-12", signed_by="the cardholder",
                             tracking_id="BLU917986433", carrier="Blue Dart"),
        "art_comm": artifact("art_comm", "customer_communication",
                             channel="email", last_message_at="2026-03-14"),
    }

    class OneBadSupporting:
        name = "test"

        def draft(self, artifacts, required, case):
            return [
                claim("Delivered on 2026-03-12.", "art_ship.delivered_at"),
                claim("Corresponded on 2026-09-09.", "art_comm.last_message_at",
                      api_field="customer_communication", required=False),
            ]

    result = draft_representment(arts, ("shipping_proof",), {"dispute_id": "d1"},
                                 provider=OneBadSupporting())
    assert not result.blocked
    assert len(result.stripped) == 1
    assert result.coverage_after == 1.0


# ------------------------------------------------------------------ assembly


def test_the_summary_respects_the_api_limit_and_prioritises_required_claims():
    """If something must be dropped for length it is the supporting colour, never
    the required document the issuer is looking for."""
    long_supporting = [
        Claim(f"clm_s{i}", "S" * 200, (Citation("a", "f"),), {}, "customer_communication", False)
        for i in range(10)
    ]
    required_claim = Claim("clm_r", "R" * 100, (Citation("a", "f"),), {},
                           "shipping_proof", True)
    summary, truncated = assemble_summary(long_supporting + [required_claim])
    assert len(summary) <= SUMMARY_LIMIT
    assert truncated
    assert summary.startswith("R" * 100), "the required claim was not prioritised"


def test_action_is_hard_coded_to_draft_and_never_submit():
    """Hard rule 3, checked at the payload boundary."""
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}
    result = draft_representment(arts, (), {"dispute_id": "d1"})
    body = contest_payload({"shipping_proof": ["doc_1"]}, result, 1_840_000)
    assert body["action"] == "draft"
    assert "submit" not in str(body).lower()


def test_a_blocked_draft_still_returns_a_payload_carrying_its_reason():
    """Returning nothing would leave the console unable to tell the merchant why
    filing did not happen, which is the one thing they need to know."""
    arts = {"art_ship": artifact(delivered_at="2026-03-12")}

    class Fabricator:
        name = "test"

        def draft(self, artifacts, required, case):
            return [claim("Delivered on 2026-09-09.", "art_ship.delivered_at")]

    result = draft_representment(arts, ("shipping_proof",), {"dispute_id": "d1"},
                                 provider=Fabricator())
    body = contest_payload({}, result, 1_840_000)
    assert body["action"] == "draft"
    assert body["summary"] == ""
    assert body["blocked_reason"]


# ------------------------------------------------------------------ providers


def test_the_templated_provider_cannot_fabricate_by_construction(corpus_row):
    """Every sentence is assembled FROM the field values it cites, so there is no
    path by which a number reaches the prose without coming from a cited field.
    Verified rather than assumed, because that property is easy to lose."""
    arts = synthesize(
        corpus_row["dispute_id"], corpus_row["evidence_fields_present"],
        created_at=corpus_row["created_at"],
        payment_created_at=corpus_row["payment_created_at"],
        amount_minor=corpus_row["amount_minor"],
    )
    claims = TemplatedProvider().draft(arts, (), {"dispute_id": corpus_row["dispute_id"]})
    assert claims, "no claims drafted for a case with evidence"
    for c in claims:
        assert verify_claim(c, arts) is None, f"templated provider emitted: {c.text}"


def test_the_verifier_catches_every_injected_fault(corpus_row):
    """Fault injection against our own verifier - NOT a measurement of any
    model's error rate, and nothing here claims one. What is asserted is that
    this class of error is caught, which is a claim about the verifier."""
    arts = synthesize(
        corpus_row["dispute_id"], corpus_row["evidence_fields_present"],
        created_at=corpus_row["created_at"],
        payment_created_at=corpus_row["payment_created_at"],
        amount_minor=corpus_row["amount_minor"],
    )
    claims = FaultInjectingProvider(rate=1.0).draft(
        arts, (), {"dispute_id": corpus_row["dispute_id"]})
    assert claims
    for c in claims:
        assert verify_claim(c, arts) is not None, f"a fault reached the payload: {c.text}"


def test_drafting_is_reproducible(corpus_row):
    """A caught fabrication that cannot be reproduced is an anecdote. Seeded, so
    a screenshot of one survives."""
    kwargs = dict(
        created_at=corpus_row["created_at"],
        payment_created_at=corpus_row["payment_created_at"],
        amount_minor=corpus_row["amount_minor"],
    )
    a = synthesize(corpus_row["dispute_id"], corpus_row["evidence_fields_present"], **kwargs)
    b = synthesize(corpus_row["dispute_id"], corpus_row["evidence_fields_present"], **kwargs)
    assert {k: v.fields for k, v in a.items()} == {k: v.fields for k, v in b.items()}

    case = {"dispute_id": corpus_row["dispute_id"]}
    p = FaultInjectingProvider(rate=0.5)
    assert [c.text for c in p.draft(a, (), case)] == [c.text for c in p.draft(b, (), case)]


def test_groundedness_is_one_by_construction_but_measured_anyway(corpus_row):
    """A number that is 1.0 by construction is only meaningful if it is measured
    rather than asserted, so it is measured."""
    arts = synthesize(
        corpus_row["dispute_id"], corpus_row["evidence_fields_present"],
        created_at=corpus_row["created_at"],
        payment_created_at=corpus_row["payment_created_at"],
        amount_minor=corpus_row["amount_minor"],
    )
    result = draft_representment(arts, (), {"dispute_id": corpus_row["dispute_id"]})
    assert not result.blocked
    assert result.groundedness == 1.0


def test_synthesized_artifacts_sit_inside_the_case_timeline(corpus_row):
    """The constraint layer refuses a delivery that post-dates its dispute, so
    values that ignored the timeline would produce artifacts the rest of the
    system would rightly reject."""
    arts = synthesize(
        corpus_row["dispute_id"], corpus_row["evidence_fields_present"],
        created_at=corpus_row["created_at"],
        payment_created_at=corpus_row["payment_created_at"],
        amount_minor=corpus_row["amount_minor"],
    )
    paid = corpus_row["payment_created_at"][:10]
    disputed = corpus_row["created_at"][:10]
    for art in arts.values():
        for name in ("delivered_at", "rendered_at", "last_message_at", "refunded_at"):
            if name in art.fields:
                assert paid <= art.fields[name] <= disputed, f"{art.artifact_id}.{name}"


@pytest.fixture(scope="module")
def corpus_row():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "corpus" / "disputes.jsonl"
    if not path.exists():
        pytest.skip("corpus not generated; run `make data`")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["evidence_sufficient"] and len(row["evidence_fields_present"]) >= 3:
                return row
    pytest.skip("no suitable row in corpus")
