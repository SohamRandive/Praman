"""The matrix must stay tied to the documentation it claims to encode.

Building the evidence engine before the generator removed a duplicated rule
that would have drifted, at one cost: the corpus can no longer reveal that the
engine has *misread* the documentation, because the corpus now derives
`evidence_sufficient` from this very file. A shared misreading propagates
silently into every downstream number. Verification is therefore higher-stakes
than it would otherwise be, and stale verification is a build failure.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from praman.evidence import MatrixError, ReasonCodeMatrix

MATRIX = ReasonCodeMatrix.load()


def test_source_verified_on_is_set_and_fresh():
    problems = MATRIX.verification_problems()
    assert not problems, f"{problems}. Re-check the matrix against the live docs."


def test_the_freshness_check_actually_fails_when_stale():
    """A guard nobody has watched fail is a guard nobody should trust."""
    stale = MATRIX.verification_age_days() or 0
    future = date.today() + timedelta(days=stale + 400)
    assert MATRIX.verification_problems(today=future), "staleness is not detected"


def test_source_records_both_documentation_urls():
    src = MATRIX.source
    assert "submit-evidence" in src["submit_evidence"]
    assert "disputes/contest" in src["contest_api"]
    assert src["verified_findings"], "no findings recorded from the verification pass"
    assert src["known_gaps"], "no coverage gaps recorded"


def test_every_deviation_from_the_docs_is_declared_with_a_reason():
    """Where this file departs from the published list, it must say so. The
    required/supporting split is our judgement and the docs publish a flat list,
    so silence would read as documentation when it is opinion."""
    for code, spec in MATRIX.codes.items():
        ver = spec.get("verification")
        if ver is None:
            continue
        assert ver["status"] in MATRIX.VALID_VERIFICATION
        assert len(ver["note"].split()) >= 12, f"{code}: note is too thin to be useful"


def test_the_load_time_validator_rejects_an_undeclared_status():
    raw = {
        "schema_version": 2,
        "scoring": {"required_weight": 1.0, "supporting_weight": 0.3},
        "evidence_fields": ["shipping_proof"],
        "reason_codes": {
            "X": {"network": "visa", "title": "t", "required": [], "supporting": [],
                  "verification": {"status": "probably_fine", "note": "x" * 60}},
        },
    }
    with pytest.raises(MatrixError, match="not one of"):
        ReasonCodeMatrix(raw)


def test_the_email_channel_rule_is_published_not_inferred():
    """RZP06/RZP00 email_channel_only is the single most load-bearing rule in
    the matrix. The docs state it verbatim: "Customer communications over email
    (not WhatsApp)". If that ever stops being true, this rule becomes ours."""
    findings = " ".join(MATRIX.source["verified_findings"]).lower()
    assert "not whatsapp" in findings and "verbatim" in findings
    for code in ("RZP06", "RZP00"):
        ids = {c["id"] for c in MATRIX.codes[code]["constraints"]}
        assert "email_channel_only" in ids


def test_every_constraint_declares_whether_it_is_published_or_ours():
    """The required/supporting split is already our judgement. A constraint that
    does not say which it is reads as documentation when it may be opinion."""
    for code, spec in MATRIX.codes.items():
        for con in spec.get("constraints") or []:
            assert con["source"] in ("published", "inferred"), f"{code}/{con['id']}"
            assert len(con["basis"].split()) >= 8, f"{code}/{con['id']}: basis too thin"


def test_the_email_channel_rule_is_marked_published():
    for code in ("RZP06", "RZP00"):
        con = next(c for c in MATRIX.codes[code]["constraints"]
                   if c["id"] == "email_channel_only")
        assert con["source"] == "published"
        assert "not WhatsApp" in con["basis"]


def test_the_legibility_gate_is_marked_as_ours():
    """1101, 1102 and 1103 have an identical published evidence list. The OCR
    gate is argued from the code's name, not read off the documentation, and
    saying so is the point of the field."""
    con = next(c for c in MATRIX.codes["1101"]["constraints"]
               if c["id"] == "legibility_check")
    assert con["source"] == "inferred"
    assert "identical" in con["basis"]


def test_a_constraint_without_a_declared_source_is_refused_at_load():
    raw = {
        "schema_version": 2,
        "scoring": {"required_weight": 1.0, "supporting_weight": 0.3},
        "evidence_fields": ["shipping_proof"],
        "reason_codes": {
            "X": {
                "network": "visa", "title": "t", "required": ["shipping_proof"],
                "supporting": [],
                "constraints": [{
                    "id": "c", "kind": "cross_field", "severity": "blocking",
                    "predicate": {"op": "is_true", "left": "shipping_proof.x"},
                }],
            },
        },
    }
    with pytest.raises(MatrixError, match="published \\| inferred"):
        ReasonCodeMatrix(raw)
