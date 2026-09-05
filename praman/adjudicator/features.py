"""Feature extraction, behind an allowlist that cannot reach a label.

The hard rule this file exists to enforce: anything prefixed `gt_` is
evaluation-only, and `observed_won` is the training label. One leaked column
invalidates every number downstream and it is the easiest mistake in the
project to make, so the guard is a deny-list checked at extraction time rather
than a comment asking future readers to be careful.

Missingness is a feature, not an absence. "We could not reach the courier API"
is itself predictive, and the model is given an explicit indicator for it
rather than being handed a silent zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from praman.network import EMPTY as EMPTY_COMPONENT

# Columns no model may ever see.
#
# `gt_` is enforced by prefix, so a ground-truth column added to the generator
# tomorrow is refused without anyone remembering to update a list.
#
# The oracle group columns are the subtler case and they got through the first
# time. `in_group`, `group_size` and `group_merchant_span` carry no `gt_` prefix
# and are not labels, but they are the generator's own record of how it built
# each cluster - `group_size` is literally `len(member_ids)`. A production
# system cannot know them; it has to infer clusters from the entity graph.
# Handing them to the model turns a network-features ablation into a
# measurement of perfect cluster knowledge, which is unbeatable by construction.
#
# The test is not whether a column looks like a label. It is whether the
# production system could know it at the moment the dispute arrives.
FORBIDDEN_EXACT = frozenset({
    "observed_won",
    "in_group", "group_size", "group_merchant_span", "group_id",
    "claimant_archetype",  # who the claimant "really is" - never observable
})
FORBIDDEN_PREFIX = "gt_"

# Evidence fields tracked individually. Per-field presence is what makes a
# recommendation explainable to a merchant: "you are missing the signed
# delivery confirmation" beats "your completeness score is 0.62".
TRACKED_FIELDS = (
    "shipping_proof",
    "billing_proof",
    "customer_communication",
    "proof_of_service",
    "refund_confirmation",
    "access_activity_log",
    "refund_cancellation_policy",
    "term_and_conditions",
)

NETWORKS = ("visa", "mastercard", "rupay", "amex", "razorpay")
PHASES = ("chargeback", "pre_arbitration", "arbitration")
ARCHETYPES = (
    "d2c_apparel", "saas_subscription", "food_delivery", "electronics", "thin_records_smb",
)
CHANNELS = ("email", "whatsapp", "phone")


class LeakageError(RuntimeError):
    """Raised when a forbidden column reaches the feature layer."""


@dataclass(frozen=True)
class FeatureSpec:
    names: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.names)


def _amount_band(minor: int) -> int:
    """Amount matters through the decision threshold C/A, so the model gets a
    coarse band rather than a raw rupee figure it would happily overfit."""
    for i, edge in enumerate((25_000, 100_000, 300_000, 1_000_000, 5_000_000)):
        if minor < edge:
            return i
    return 5


def extract(row: dict[str, Any], component: dict[str, float] | None = None) -> dict[str, float]:
    """One dispute -> a flat, named feature dict.

    Every key here must be derivable at decision time, when the dispute has just
    arrived and nothing about its outcome is known. `component` carries the
    point-in-time entity-graph statistics from `praman.network`, derived from
    shared salted entities rather than read off the generator.
    """
    present = {f: float(f in row["evidence_fields_present"]) for f in TRACKED_FIELDS}
    required = set(row["required_fields"])

    feats: dict[str, float] = {
        # --- evidence coverage
        "completeness_score": float(row["completeness_score"]),
        "required_coverage": float(row["required_coverage"]),
        "evidence_field_count": float(row["evidence_field_count"]),
        "required_field_count": float(len(required)),
        "no_blocking_gaps": float(row["no_blocking_gaps"]),
        "blocking_gap_count": float(len(row["blocking_gaps"])),
        "evidence_sufficient": float(row["evidence_sufficient"]),
        "n_violated_constraints": float(len(row["violated_constraints"])),
        "n_warnings": float(len(row["warnings"])),
        "n_rejected_artifacts": float(len(row["rejected_artifacts"])),
        # --- evidence quality
        "signature_present": float(row["signature_present"]),
        # --- payment and dispute shape
        "amount_band": float(_amount_band(row["amount_minor"])),
        "payment_captured": float(row["payment_captured"]),
        # --- network signal, DERIVED from the entity graph, never declared
        **(component or EMPTY_COMPONENT),
        # --- missingness, explicit rather than silent
        "missing_classification": float(row["classification_confidence"] is None),
        "classification_confidence": float(row["classification_confidence"] or 0.0),
        "routed_to_human": float(row["routing"] == "route_to_human"),
        "comms_channel_unknown": float(row["comms_channel"] is None),
    }
    for f in TRACKED_FIELDS:
        feats[f"has_{f}"] = present[f]
        feats[f"needs_{f}"] = float(f in required)
        # The interaction that actually matters: required and absent.
        feats[f"gap_{f}"] = float(f in required and not present[f])
    for n in NETWORKS:
        feats[f"network_{n}"] = float(row["network"] == n)
    for p in PHASES:
        feats[f"phase_{p}"] = float(row["phase"] == p)
    for a in ARCHETYPES:
        feats[f"archetype_{a}"] = float(row["merchant_archetype"] == a)
    for ch in CHANNELS:
        feats[f"comms_{ch}"] = float(row["comms_channel"] == ch)
    return feats


def guard(names: object) -> None:
    """Refuse any forbidden column, by exact name or by `gt_` prefix."""
    leaked = sorted(
        n for n in names
        if n in FORBIDDEN_EXACT or n.startswith(FORBIDDEN_PREFIX)
    )
    if leaked:
        raise LeakageError(
            f"forbidden columns reached the feature layer: {leaked}. "
            f"Anything prefixed {FORBIDDEN_PREFIX!r} is evaluation-only and "
            f"{sorted(FORBIDDEN_EXACT)} is the training label."
        )


def spec(rows: list[dict[str, Any]]) -> FeatureSpec:
    names = tuple(sorted(extract(rows[0])))
    guard(names)
    return FeatureSpec(names)


def matrix(
    rows: list[dict[str, Any]],
    fs: FeatureSpec,
    components: dict[str, dict[str, float]] | None = None,
) -> list[list[float]]:
    guard(fs.names)
    components = components or {}
    out = []
    for row in rows:
        f = extract(row, components.get(row["dispute_id"]))
        out.append([f[n] for n in fs.names])
    return out


def labels(rows: list[dict[str, Any]]) -> list[int]:
    """The training label is the noisy one the merchant actually gets back."""
    return [int(r["observed_won"]) for r in rows]
