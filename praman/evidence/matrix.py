"""Load and resolve the reason-code evidence matrix.

Resolution answers one question: for *this* case, which contest() evidence
fields are required, which merely help, and which constraints apply. Two codes
cannot answer it from the code alone:

  branch                  RZP05 forks on payment.captured, a fact already on the
                          payment object. No model is involved.
  classify_then_delegate  4853/4854/RZP00 do not name the sub-claim. The engine
                          never classifies; it accepts a classification from the
                          caller and gates it on confidence, so the model stays
                          outside the deterministic core.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .constraints import (
    CONTEXT_ROOTS,
    MISSING,
    ConstraintError,
    resolve_operand,
    validate_predicate,
)
from .types import CaseContext, Classification, ResolvedRequirements

DEFAULT_MATRIX_PATH = Path(__file__).resolve().parents[2] / "data" / "reason_codes.yaml"
MAX_DELEGATION_DEPTH = 3


class MatrixError(ValueError):
    pass


class ReasonCodeMatrix:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self.schema_version: int = raw["schema_version"]
        self.source: dict[str, Any] = raw.get("source", {})
        self.scoring: dict[str, Any] = raw["scoring"]
        self.evidence_fields: tuple[str, ...] = tuple(raw["evidence_fields"])
        self.codes: dict[str, dict[str, Any]] = raw["reason_codes"]
        self._validate()

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: str | Path | None = None) -> ReasonCodeMatrix:
        path = Path(path) if path else DEFAULT_MATRIX_PATH
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    VALID_VERIFICATION = frozenset({"verified", "deviates", "judgement", "unpublished"})

    def verification_age_days(self, today: date | None = None) -> int | None:
        """Days since the matrix was last checked against the live documentation.

        None when it has never been checked. The generator derives
        `evidence_sufficient` from this file, so a misreading here propagates
        into every downstream number without contradicting anything - which is
        exactly why staleness has to be a build failure rather than a habit.
        """
        checked = self.source.get("source_verified_on")
        if not checked:
            return None
        if isinstance(checked, str):
            checked = date.fromisoformat(checked)
        return ((today or date.today()) - checked).days

    def verification_problems(self, today: date | None = None) -> list[str]:
        age = self.verification_age_days(today)
        if age is None:
            return ["source.source_verified_on is not set"]
        limit = int(self.source.get("max_age_days", 30))
        if age > limit:
            return [f"matrix last verified {age} days ago, limit is {limit}"]
        if age < 0:
            return [f"source_verified_on is {-age} days in the future"]
        return []

    def _validate(self) -> None:
        """Fail loudly at load time so no malformed rule can fail quietly later."""
        collisions = set(self.evidence_fields) & set(CONTEXT_ROOTS)
        if collisions:
            raise MatrixError(
                f"evidence fields collide with constraint operand roots: {collisions}"
            )
        known = set(self.evidence_fields)
        for code, spec in self.codes.items():
            ver = spec.get("verification")
            if ver is not None:
                if ver.get("status") not in self.VALID_VERIFICATION:
                    raise MatrixError(
                        f"{code}: verification status {ver.get('status')!r} is not one of "
                        f"{sorted(self.VALID_VERIFICATION)}"
                    )
                if not (ver.get("note") or "").strip():
                    raise MatrixError(f"{code}: verification without a note explaining it")
            for key in ("network", "title", "required", "supporting"):
                if key not in spec:
                    raise MatrixError(f"{code}: missing {key!r}")
            for fld in list(spec["required"]) + list(spec["supporting"]):
                if fld.split(".", 1)[0] not in known:
                    raise MatrixError(f"{code}: {fld!r} is not a contest() evidence field")
            for con in spec.get("constraints") or []:
                if "id" not in con:
                    raise MatrixError(f"{code}: constraint without an id")
                where = f"{code}/{con['id']}"
                if con.get("severity") not in ("blocking", "warn"):
                    raise MatrixError(f"{where}: severity must be blocking or warn")
                if con.get("kind") == "field_qualifier" and "field" not in con:
                    raise MatrixError(f"{where}: field_qualifier needs a `field`")
                # Published or ours - never silent. The required/supporting split
                # is already our judgement; a constraint that does not say which
                # it is reads as documentation when it may be opinion.
                if con.get("source") not in ("published", "inferred"):
                    raise MatrixError(
                        f"{where}: constraint must declare source: published | inferred"
                    )
                if not (con.get("basis") or "").strip():
                    raise MatrixError(f"{where}: constraint source needs a `basis`")
                try:
                    validate_predicate(con["predicate"], where)
                except ConstraintError as exc:
                    raise MatrixError(str(exc)) from exc
            res = spec.get("resolution")
            if res:
                strategy = res.get("strategy")
                if strategy == "branch":
                    if "branch_on" not in res or "branches" not in res:
                        raise MatrixError(f"{code}: branch resolution needs `branch_on` and `branches`")
                elif strategy == "classify_then_delegate":
                    missing = [c for c in res.get("candidates", []) if c not in self.codes]
                    if missing:
                        raise MatrixError(f"{code}: delegates to unknown codes {missing}")
                    if not res.get("candidates"):
                        raise MatrixError(f"{code}: classify_then_delegate with no candidates")
                else:
                    raise MatrixError(f"{code}: unknown resolution strategy {strategy!r}")

    # -------------------------------------------------------------- resolve

    def resolve(
        self,
        reason_code: str,
        context: CaseContext | None = None,
        classification: Classification | None = None,
        _depth: int = 0,
    ) -> ResolvedRequirements:
        if reason_code not in self.codes:
            raise MatrixError(f"unknown reason code {reason_code!r}")
        context = context or CaseContext()
        spec = self.codes[reason_code]

        base = ResolvedRequirements(
            reason_code=reason_code,
            resolved_code=reason_code,
            network=spec["network"],
            title=spec["title"],
            required=tuple(spec["required"]),
            supporting=tuple(spec["supporting"]),
            constraints=tuple(spec.get("constraints") or []),
        )

        res = spec.get("resolution")
        if not res:
            return base
        if _depth >= MAX_DELEGATION_DEPTH:
            return replace(
                base,
                routing="route_to_human",
                unresolved_reason=f"delegation exceeded depth {MAX_DELEGATION_DEPTH}",
            )

        if res["strategy"] == "branch":
            return self._resolve_branch(base, res, context)
        return self._resolve_delegate(base, res, context, classification, _depth)

    def _resolve_branch(
        self, base: ResolvedRequirements, res: dict[str, Any], context: CaseContext
    ) -> ResolvedRequirements:
        value, detail = resolve_operand(res["branch_on"], context, {})
        if value is MISSING:
            return replace(
                base,
                routing="route_to_human",
                unresolved_reason=(
                    f"cannot branch on {res['branch_on']}: {detail}. Which argument to make "
                    f"depends on it, so the case is routed rather than guessed."
                ),
            )
        key = str(bool(value)).lower()
        branch = res["branches"].get(key)
        if branch is None:
            return replace(
                base, routing="route_to_human", unresolved_reason=f"no branch for {key!r}"
            )
        return replace(
            base,
            required=tuple(branch["required"]),
            supporting=tuple(branch["supporting"]),
            resolution_note=(
                f"branch {res['branch_on']}={value!r} -> argue {branch['argument']}"
            ),
        )

    def _resolve_delegate(
        self,
        base: ResolvedRequirements,
        res: dict[str, Any],
        context: CaseContext,
        classification: Classification | None,
        depth: int,
    ) -> ResolvedRequirements:
        floor = float(res.get("min_confidence", 0.7))
        if classification is None:
            return replace(
                base,
                routing="route_to_human",
                unresolved_reason=(
                    f"{base.reason_code} does not name the sub-claim and no "
                    f"classification was supplied"
                ),
            )
        if classification.code not in res["candidates"]:
            return replace(
                base,
                routing="route_to_human",
                unresolved_reason=(
                    f"classified as {classification.code}, which is not a candidate "
                    f"for {base.reason_code}"
                ),
            )
        if classification.confidence < floor:
            return replace(
                base,
                routing="route_to_human",
                unresolved_reason=(
                    f"classified {classification.code} at {classification.confidence:.2f}, "
                    f"below the {floor:.2f} floor"
                ),
            )

        child = self.resolve(classification.code, context, _depth=depth + 1)
        # The parent's own constraints survive delegation: RZP00 delegates its
        # sub-claim but its email_channel_only rule still governs the package.
        seen = {c["id"] for c in base.constraints}
        merged = list(base.constraints) + [c for c in child.constraints if c["id"] not in seen]
        return replace(
            base,
            resolved_code=child.resolved_code,
            required=child.required,
            supporting=child.supporting,
            constraints=tuple(merged),
            routing=child.routing,
            unresolved_reason=child.unresolved_reason,
            resolution_note=(
                f"delegated {base.reason_code} -> {classification.code} "
                f"at confidence {classification.confidence:.2f}"
                + (f"; {child.resolution_note}" if child.resolution_note else "")
            ),
        )
