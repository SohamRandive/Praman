"""Corpus generator: seeded, reproducible, and auditable.

Ground truth is *factored*, never asserted:

    gt_winnable = (not merchant_at_fault) and evidence_sufficient

The halves are generated independently. `merchant_at_fault` comes from the
merchant's fulfilment reliability and the claimant's grievance prior - a fact
about the world. `evidence_sufficient` comes from resolving the reason code
against the published matrix with the real evidence engine - a fact about
record-keeping. A merchant can be entirely in the right and lose because nobody
kept a signed delivery record; a merchant with immaculate records can lose
because they genuinely failed to deliver. Keeping the two separable is what
stops a model learning a shortcut.

The observed label is drawn by passing ground truth through a noisy issuer.
Train on `observed_won`. Never on any `gt_` column.

    python3 build.py --out ../corpus --seed 20260904
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data.generator.archetypes import (  # noqa: E402
    CLAIMANT_ARCHETYPES,
    CORPUS_DAYS,
    CORPUS_START,
    DECOY_PROFILES,
    ECONOMICS,
    ISSUER_NOISE,
    MERCHANT_ARCHETYPES,
    PHASE_WEIGHTS,
    RESPOND_BY_DAYS,
    RING_PROFILES,
    SPLIT_RATIOS,
    ClaimantArchetype,
)
from praman.evidence import (  # noqa: E402
    CaseContext,
    Classification,
    EvidenceArtifact,
    ReasonCodeMatrix,
    assemble,
)

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime.fromisoformat(CORPUS_START).replace(tzinfo=IST)

# Codes whose sub-claim the issuer does not name. The generator supplies a
# classification exactly as the runtime will, so the corpus exercises the same
# delegation path the system takes in production.
DELEGATION_CANDIDATES = {
    "4853": ["13.1", "13.3", "13.6", "13.7"],
    "4854": ["13.1", "13.3", "13.6", "13.7"],
    "RZP00": ["RZP01", "RZP04", "RZP05", "RZP06"],
}


# ------------------------------------------------------------------ helpers


def stable_seed(*parts: object) -> int:
    """A process-stable hash. Python's built-in hash() is randomised per run for
    strings, which would silently break bit-reproducibility."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def salted(salt: str, kind: str, value: object) -> str:
    """Salted hash for every entity id. No raw identifier reaches an output
    file, so the graph cannot be inverted to a real person."""
    digest = hashlib.blake2b(f"{salt}|{kind}|{value}".encode(), digest_size=12)
    return f"{kind[:3]}_{digest.hexdigest()}"


def rzp_id(prefix: str, rng: random.Random) -> str:
    """Razorpay identifier shape: prefix plus 14 alphanumerics."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return prefix + "".join(rng.choice(alphabet) for _ in range(14))


def allocate(n: int, ratios: dict[str, float]) -> dict[str, int]:
    """Largest-remainder allocation.

    Naive int(n * ratio) flooring starved calibration to 4% of the corpus when
    15% was requested: with 12 merchants per archetype, int(12 * 0.15) is 1.
    """
    raw = {k: n * v for k, v in ratios.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    remaining = n - sum(out.values())
    order = sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))
    for i in range(remaining):
        out[order[i % len(order)]] += 1
    assert sum(out.values()) == n
    return out


def pick_weighted(rng: random.Random, weights: dict[str, float]) -> str:
    keys = sorted(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def uniform_in(rng: random.Random, span: tuple[float, float]) -> float:
    return rng.uniform(span[0], span[1])


def lognormal_minor(rng: random.Random, median_minor: int, spread_pct: int) -> int:
    return max(100, int(median_minor * math.exp(rng.gauss(0.0, spread_pct / 100.0))))


def iso(dt: datetime) -> str:
    return dt.isoformat()


# ----------------------------------------------------------------- entities


def build_merchants(salt: str, scale: float) -> list[dict[str, Any]]:
    merchants: list[dict[str, Any]] = []
    for arch in MERCHANT_ARCHETYPES:
        for i in range(arch.merchants):
            mrng = random.Random(stable_seed(salt, "merchant", arch.name, i))
            merchants.append({
                "merchant_id": rzp_id("acc_", mrng),
                "archetype": arch.name,
                "monthly_orders": max(10, int(uniform_in(mrng, arch.monthly_orders) * scale)),
                "dispute_rate": round(uniform_in(mrng, arch.dispute_rate), 5),
                "fulfilment_reliability": round(uniform_in(mrng, arch.fulfilment_reliability), 4),
                "signature_capture_rate": round(uniform_in(mrng, arch.signature_capture_rate), 4),
                "ocr_quality": round(uniform_in(mrng, arch.ocr_quality), 4),
                "order_value_minor": arch.order_value_minor,
                "hygiene": {f: round(uniform_in(mrng, s), 4) for f, s in arch.hygiene.items()},
                "support_channels": dict(arch.support_channels),
                "reason_code_weights": dict(arch.reason_code_weights),
            })
    return merchants


def merchant_quality(m: dict[str, Any]) -> float:
    """The two things that actually drive whether a dispute is winnable.

    `gt_winnable` factors into (not merchant_at_fault) and evidence_sufficient,
    driven by fulfilment reliability and record-keeping hygiene respectively.
    Those are therefore the confounder the split has to balance on.
    """
    hygiene = m["hygiene"].values()
    return m["fulfilment_reliability"] * (sum(hygiene) / len(m["hygiene"]))


def split_merchants(merchants: list[dict[str, Any]], rng: random.Random) -> None:
    """Split by merchant, stratified by archetype *and by merchant quality*.

    By merchant because evidence hygiene is a merchant-level property and a
    random row split leaks it. Stratified by archetype because merchant volume
    is heavy-tailed, and an unstratified shuffle put most corpus volume in the
    calibration split by chance on the first run.

    Stratifying by archetype alone was not enough. With 7/2/3 merchants per
    archetype, the within-archetype spread of hygiene and reliability is wide
    enough that the draw stayed lumpy: d2c_apparel came out at winnable rates of
    0.365 / 0.427 / 0.513 across train / calibration / test, a 15-point shift
    that would have shown up as spurious model degradation on the test split.
    So merchants are quality-sorted inside each archetype and dealt into the
    splits proportionally - systematic stratified sampling on the confounder.
    """
    by_arch: dict[str, list[dict[str, Any]]] = {}
    for m in merchants:
        by_arch.setdefault(m["archetype"], []).append(m)

    order = ("train", "calibration", "test")
    for arch in sorted(by_arch):
        pool = sorted(by_arch[arch], key=lambda m: m["merchant_id"])
        rng.shuffle(pool)  # breaks ties between equal-quality merchants
        pool.sort(key=merchant_quality)
        counts = allocate(len(pool), SPLIT_RATIOS)
        assigned = dict.fromkeys(order, 0)
        # Two things must balance at once, and they are independent of each
        # other: quality (which drives winnability) and volume (which is
        # heavy-tailed and drives each split's size). Walking the pool in
        # quality order spreads the first; always handing the next merchant to
        # whichever split is furthest below its volume target spreads the
        # second. Balancing only one of them moved the imbalance into the other.
        volume = {m["merchant_id"]: m["monthly_orders"] * m["dispute_rate"] for m in pool}
        total_volume = sum(volume.values()) or 1.0
        target_volume = {s: SPLIT_RATIOS[s] * total_volume for s in order}
        got_volume = dict.fromkeys(order, 0.0)
        for i, m in enumerate(pool):
            eligible = [s for s in order if assigned[s] < counts[s]]
            # The tie-break rotates. Breaking ties by name instead sent the
            # lowest-quality merchant of every archetype to the same split -
            # every split starts at zero volume, so the first comparison is
            # always a tie - and that alone depressed the calibration fold's
            # winnable rate by five points.
            best = min(
                eligible,
                key=lambda s: (got_volume[s] / target_volume[s], (order.index(s) - i) % 3),
            )
            m["split"] = best
            assigned[best] += 1
            got_volume[best] += volume[m["merchant_id"]]


def build_groups(merchants: list[dict[str, Any]], salt: str) -> list[dict[str, Any]]:
    """Rings and decoys, built by one code path (ADR-006).

    Each group lives entirely inside one split's merchant pool. A ring spanning
    train and test would leak its structure across the boundary and make
    test-split ring recall meaningless.
    """
    pools: dict[str, list[dict[str, Any]]] = {"train": [], "calibration": [], "test": []}
    for m in merchants:
        pools[m["split"]].append(m)
    split_weights = {s: float(len(pools[s])) for s in sorted(pools)}

    groups: list[dict[str, Any]] = []
    for profile in list(RING_PROFILES) + list(DECOY_PROFILES):
        for i in range(profile.count):
            grng = random.Random(stable_seed(salt, "group", profile.name, i))
            split = pick_weighted(grng, split_weights)
            pool = pools[split]
            span = min(int(uniform_in(grng, profile.merchant_span)), len(pool))
            if span < 2:
                continue
            targets = grng.sample(pool, span)
            group_id = f"grp_{profile.name[:4]}_{i:03d}"

            # The shared entity keys are what make this a connected component.
            # A household and a device farm are structurally identical here;
            # only burst and propensity separate them.
            shared = {
                kind: salted(salt, kind, f"{group_id}:{kind}")
                for kind in profile.shared_entities
            }
            members = []
            for j in range(int(uniform_in(grng, profile.members))):
                cid = f"{group_id}:m{j}"
                members.append({
                    "claimant_id": cid,
                    "identity": salted(salt, "identity", cid),
                    "device": shared.get("device", salted(salt, "device", cid)),
                    "address_geo": shared.get("address_geo", salted(salt, "address_geo", cid)),
                    "instrument": shared.get("instrument", salted(salt, "instrument", cid)),
                })

            burst = int(uniform_in(grng, profile.burst_days))
            groups.append({
                "group_id": group_id,
                "profile": profile.name,
                "is_abusive": profile.is_abusive,
                "split": split,
                "member_ids": [m["claimant_id"] for m in members],
                "members": members,
                "target_merchant_ids": [m["merchant_id"] for m in targets],
                "shared_entity_kinds": list(profile.shared_entities),
                "burst_days": burst,
                "burst_start_day": grng.randint(0, max(1, CORPUS_DAYS - burst - 1)),
                "dispute_propensity": round(uniform_in(grng, profile.dispute_propensity), 4),
            })
    return groups


# ----------------------------------------------------------------- evidence

# How often each way of losing-with-paperwork-attached actually happens. These
# rates are assumptions; they are what produce the corpus's blocking-gap rate.
VIOLATION_RATES = {
    "delivery_after_dispute": 0.075,
    "partial_refund": 0.13,
    "policy_published_late": 0.05,
    "shipped_after_cancellation": 0.16,
    "cancellation_timestamp_known": 0.62,  # else the constraint is unevaluated
}

# Fields whose absence the merchant genuinely cannot help - a SaaS business has
# no shipping proof, and pretending otherwise would fabricate a gap.
FIELD_DATE_KEYS = {
    "billing_proof": "settled_at",
    "proof_of_service": "rendered_at",
    "access_activity_log": "last_access_at",
    "term_and_conditions": "published_at",
    "explanation_letter": "written_at",
    "cancellation_proof": "cancelled_at",
}


def make_artifacts(
    rng: random.Random,
    merchant: dict[str, Any],
    fields: list[str],
    timeline: dict[str, datetime],
    amounts: dict[str, int],
) -> list[EvidenceArtifact]:
    """Retrieve what this merchant actually kept.

    Presence is drawn per field from the merchant's hygiene, which is a
    merchant-level property - which is exactly why the corpus is split by
    merchant and not by row.
    """
    artifacts: list[EvidenceArtifact] = []
    for fld in fields:
        hygiene_key = "others" if fld.startswith("others.") else fld
        prob = merchant["hygiene"].get(hygiene_key, 0.6)
        if rng.random() >= prob:
            continue

        values: dict[str, Any] = {
            "ocr_confidence": round(
                min(0.999, max(0.30, rng.gauss(merchant["ocr_quality"], 0.07))), 4
            )
        }

        if fld == "shipping_proof":
            shipped = timeline["payment"] + timedelta(days=rng.uniform(0.2, 4.0))
            if rng.random() < VIOLATION_RATES["delivery_after_dispute"]:
                delivered = timeline["dispute"] + timedelta(days=rng.uniform(0.5, 6.0))
            else:
                delivered = shipped + timedelta(days=rng.uniform(0.8, 7.0))
                if delivered >= timeline["dispute"]:
                    delivered = timeline["dispute"] - timedelta(days=rng.uniform(0.5, 3.0))
            if timeline.get("cancellation") and rng.random() < VIOLATION_RATES["shipped_after_cancellation"]:
                shipped = timeline["cancellation"] + timedelta(days=rng.uniform(0.2, 3.0))
            values |= {
                "shipped_at": iso(shipped),
                "delivered_at": iso(delivered),
                "signature_present": rng.random() < merchant["signature_capture_rate"],
                "carrier": rng.choice(["bluedart", "delhivery", "ekart", "xpressbees", "india_post"]),
            }
        elif fld == "customer_communication":
            values |= {
                "channel": pick_weighted(rng, merchant["support_channels"]),
                "last_contact_at": iso(timeline["dispute"] - timedelta(days=rng.uniform(0.5, 20))),
            }
        elif fld == "refund_confirmation":
            full = amounts["payment_minor"]
            amount = (
                int(full * rng.uniform(0.2, 0.85))
                if rng.random() < VIOLATION_RATES["partial_refund"]
                else full
            )
            values |= {
                "amount_minor": amount,
                "refunded_at": iso(timeline["dispute"] - timedelta(days=rng.uniform(0.2, 14))),
            }
        elif fld == "refund_cancellation_policy":
            late = rng.random() < VIOLATION_RATES["policy_published_late"]
            published = (
                timeline["payment"] + timedelta(days=rng.uniform(1, 40))
                if late
                else timeline["payment"] - timedelta(days=rng.uniform(30, 400))
            )
            values["published_at"] = iso(published)
        elif fld in FIELD_DATE_KEYS:
            values[FIELD_DATE_KEYS[fld]] = iso(
                timeline["payment"] + timedelta(days=rng.uniform(0, 10))
            )

        artifacts.append(EvidenceArtifact(
            artifact_id=rzp_id("doc_", rng),
            source_system={"shipping_proof": "courier_api",
                           "customer_communication": "support_desk",
                           "refund_confirmation": "payments_api"}.get(fld, "merchant_records"),
            artifact_type=fld,
            api_field=fld,
            content_hash=hashlib.blake2b(fld.encode(), digest_size=8).hexdigest(),
            retrieved_at=iso(timeline["dispute"] + timedelta(hours=rng.uniform(1, 30))),
            fields=values,
        ))
    return artifacts


# ----------------------------------------------------------------- disputes


def mean_unreliability() -> float:
    """Average P(merchant at fault) across archetypes, used to recentre the
    claimant prior so a merchant's reliability modulates it rather than
    replacing it."""
    vals = [1 - (a.fulfilment_reliability[0] + a.fulfilment_reliability[1]) / 2
            for a in MERCHANT_ARCHETYPES]
    return sum(vals) / len(vals)


MEAN_UNRELIABILITY = mean_unreliability()


def draw_merchant_fault(
    rng: random.Random, merchant: dict[str, Any], claimant: ClaimantArchetype
) -> bool:
    """A fact about the world, drawn independently of any record-keeping.

    This is why evidence features cannot solve the task: nothing in a document
    cupboard observes whether the merchant actually failed the customer.
    """
    ratio = (1 - merchant["fulfilment_reliability"]) / MEAN_UNRELIABILITY
    p = min(0.98, max(0.005, claimant.merchant_fault_prior * ratio))
    return rng.random() < p


def draw_observed(rng: random.Random, winnable: bool, phase: str, filed_late: bool) -> bool:
    """Pass ground truth through a noisy issuer (ADR-007).

    Training on noiseless truth produces a model that is confidently wrong and a
    calibration curve that flatters the system. The AUC ceiling this creates is
    the point, not a defect.
    """
    p = (1 - ISSUER_NOISE.false_loss_rate) if winnable else ISSUER_NOISE.false_win_rate
    if filed_late:
        p *= 1 - ISSUER_NOISE.late_filing_penalty
    if phase != "chargeback":
        p *= 1 - ISSUER_NOISE.phase_escalation_penalty
    return rng.random() < p


def solo_claimant(rng: random.Random, salt: str, merchant_id: str, i: int) -> dict[str, Any]:
    cid = f"solo:{merchant_id}:{i}"
    return {
        "claimant_id": cid,
        "identity": salted(salt, "identity", cid),
        "device": salted(salt, "device", cid),
        "address_geo": salted(salt, "address_geo", cid),
        "instrument": salted(salt, "instrument", cid),
    }


CANCELLATION_CODES = {"13.7", "C05"}
NETWORK_OF = {"visa": "visa", "mastercard": "mastercard", "rupay": "rupay",
              "amex": "amex", "razorpay": "razorpay"}


def generate_dispute(
    rng: random.Random,
    matrix: ReasonCodeMatrix,
    merchant: dict[str, Any],
    claimant: dict[str, Any],
    claimant_arch: ClaimantArchetype,
    code: str,
    day_offset: float,
    group: dict[str, Any] | None,
) -> dict[str, Any]:
    amount = lognormal_minor(rng, *merchant["order_value_minor"])
    dispute_at = START + timedelta(days=day_offset, hours=rng.uniform(0, 24))
    payment_at = dispute_at - timedelta(days=rng.uniform(5, 70))
    respond_by = dispute_at + timedelta(days=rng.uniform(*RESPOND_BY_DAYS))
    sla_due = payment_at + timedelta(days=rng.uniform(3, 9))

    timeline = {"payment": payment_at, "dispute": dispute_at}
    cancellation_at = None
    if code in CANCELLATION_CODES and rng.random() < VIOLATION_RATES["cancellation_timestamp_known"]:
        cancellation_at = payment_at + timedelta(days=rng.uniform(1, 20))
        timeline["cancellation"] = cancellation_at

    captured = rng.random() < 0.88
    phase = pick_weighted(rng, PHASE_WEIGHTS)

    context = CaseContext(
        dispute={
            "amount_minor": amount,
            "created_at": iso(dispute_at),
            "cancellation_requested_at": iso(cancellation_at) if cancellation_at else None,
        },
        payment={"amount_minor": amount, "created_at": iso(payment_at), "captured": captured},
        order={"sla_due_at": iso(sla_due)},
        merchant={"archetype": merchant["archetype"]},
    )

    # Codes that do not name their sub-claim get a classification, exactly as
    # the runtime supplies one. Confidence is drawn so some fall below the
    # floor and route to a human, which is the behaviour we want represented.
    classification = None
    if code in DELEGATION_CANDIDATES:
        classification = Classification(
            code=rng.choice(DELEGATION_CANDIDATES[code]),
            confidence=round(rng.betavariate(6, 2), 4),
        )

    reqs = matrix.resolve(code, context, classification)
    artifacts = make_artifacts(
        rng, merchant, list(reqs.required) + list(reqs.supporting), timeline,
        {"payment_minor": amount},
    )
    package = assemble(reqs, artifacts, context, matrix.scoring)

    merchant_at_fault = draw_merchant_fault(rng, merchant, claimant_arch)
    gt_winnable = (not merchant_at_fault) and package.sufficient

    # Filing lateness is NOT a feature: at decision time nobody knows how late
    # the merchant will file. It exists only to add realistic label noise.
    filed_late = rng.random() < (0.34 if merchant["archetype"] == "thin_records_smb" else 0.14)
    observed_won = draw_observed(rng, gt_winnable, phase, filed_late)

    present = {f: bool(package.bound.get(f)) for f in reqs.required}
    return {
        "dispute_id": rzp_id("disp_", rng),
        "payment_id": rzp_id("pay_", rng),
        "order_id": rzp_id("order_", rng),
        "merchant_id": merchant["merchant_id"],
        "merchant_archetype": merchant["archetype"],
        "split": merchant["split"],

        "claimant_id": claimant["claimant_id"],
        "claimant_archetype": claimant_arch.name,
        "identity_hash": claimant["identity"],
        "device_hash": claimant["device"],
        "address_hash": claimant["address_geo"],
        "instrument_hash": claimant["instrument"],

        "reason_code": code,
        "resolved_code": package.resolved_code,
        "network": NETWORK_OF[reqs.network],
        "phase": phase,
        "amount_minor": amount,
        "currency": "INR",
        "created_at": iso(dispute_at),
        "respond_by": iso(respond_by),
        "payment_created_at": iso(payment_at),
        "payment_captured": captured,
        "classification_confidence": classification.confidence if classification else None,

        # --- observable features: everything below is available at decision time
        "required_fields": list(reqs.required),
        "evidence_fields_present": sorted(package.bound),
        "evidence_field_count": len(package.bound),
        "required_present": present,
        "completeness_score": package.completeness_score,
        "required_coverage": package.required_coverage,
        "no_blocking_gaps": not package.blocking_gaps,
        "blocking_gaps": [g.name for g in package.blocking_gaps],
        "violated_constraints": package.violated_constraints,
        "unevaluated_constraints": [f"unevaluated:{c}" for c in package.unevaluated_constraints],
        "warnings": [w.constraint_id for w in package.warnings],
        "rejected_artifacts": [
            {"constraint_id": r.constraint_id, "api_field": r.api_field} for r in package.rejected
        ],
        "evidence_sufficient": package.sufficient,
        "routing": package.routing,
        "signature_present": any(
            a.fields.get("signature_present") for a in artifacts if a.api_field == "shipping_proof"
        ),
        "comms_channel": next(
            (a.fields.get("channel") for a in artifacts if a.api_field == "customer_communication"),
            None,
        ),

        # --- network features
        "group_id": group["group_id"] if group else None,
        "in_group": group is not None,
        "group_size": len(group["member_ids"]) if group else 0,
        "group_merchant_span": len(group["target_merchant_ids"]) if group else 0,

        # --- EVALUATION ONLY. Never a feature. Enforced by an allowlist in the
        #     adjudicator and by tests/test_no_ground_truth_leakage.py.
        "gt_merchant_at_fault": merchant_at_fault,
        "gt_winnable": gt_winnable,
        "gt_in_abusive_ring": bool(group and group["is_abusive"]),
        "gt_filed_late": filed_late,

        # --- the training label
        "observed_won": observed_won,
    }


def build_corpus(seed: int, target_disputes: int, salt: str) -> dict[str, Any]:
    rng = random.Random(stable_seed(salt, "root", seed))
    matrix = ReasonCodeMatrix.load()

    merchants = build_merchants(salt, scale=1.0)
    split_merchants(merchants, rng)
    groups = build_groups(merchants, salt)
    by_id = {m["merchant_id"]: m for m in merchants}
    claimant_by_name = {c.name: c for c in CLAIMANT_ARCHETYPES}

    disputes: list[dict[str, Any]] = []

    # 1. Group-driven disputes. Rings burst; decoys trickle across the window.
    for group in groups:
        grng = random.Random(stable_seed(salt, "groupdisputes", group["group_id"]))
        targets = [by_id[m] for m in group["target_merchant_ids"]]
        profile = next(
            p for p in list(RING_PROFILES) + list(DECOY_PROFILES) if p.name == group["profile"]
        )
        arch = claimant_by_name["ring_member" if group["is_abusive"] else "honest_confused"]
        for member in group["members"]:
            orders = int(uniform_in(grng, profile.orders_per_member))
            n = int(round(orders * group["dispute_propensity"]))
            for _ in range(n):
                merchant = grng.choice(targets)
                day = group["burst_start_day"] + grng.uniform(0, group["burst_days"])
                code = pick_weighted(grng, merchant["reason_code_weights"])
                disputes.append(generate_dispute(
                    grng, matrix, merchant, member, arch, code, day, group))

    # 2. Background disputes. Allocated per split so that group disputes, which
    #    land wherever their group lives, do not drag the split shares off
    #    target - that drift pulled calibration from 15% down to 12%. Inside a
    #    split, merchants receive disputes in proportion to the volume they do.
    group_per_split: dict[str, int] = dict.fromkeys(SPLIT_RATIOS, 0)
    for d in disputes:
        group_per_split[d["split"]] += 1

    natural = {
        m["merchant_id"]: m["monthly_orders"] * (CORPUS_DAYS / 30.0) * m["dispute_rate"]
        for m in merchants
    }
    per_merchant: dict[str, int] = dict.fromkeys(natural, 0)
    for split, ratio in SPLIT_RATIOS.items():
        pool = [m for m in merchants if m["split"] == split]
        want = max(0, int(round(target_disputes * ratio)) - group_per_split[split])
        total = sum(natural[m["merchant_id"]] for m in pool) or 1.0
        per_merchant |= allocate(want, {m["merchant_id"]: natural[m["merchant_id"]] / total
                                        for m in pool})

    solo_weights = {c.name: c.share for c in CLAIMANT_ARCHETYPES if c.name != "ring_member"}
    for merchant in merchants:
        mrng = random.Random(stable_seed(salt, "background", merchant["merchant_id"]))
        for i in range(per_merchant[merchant["merchant_id"]]):
            arch = claimant_by_name[pick_weighted(mrng, solo_weights)]
            claimant = solo_claimant(mrng, salt, merchant["merchant_id"], i)
            code = pick_weighted(mrng, merchant["reason_code_weights"])
            day = mrng.uniform(0, CORPUS_DAYS)
            disputes.append(generate_dispute(
                mrng, matrix, merchant, claimant, arch, code, day, None))

    disputes.sort(key=lambda d: (d["created_at"], d["dispute_id"]))
    return {"merchants": merchants, "groups": groups, "disputes": disputes}


def build_entity_edges(disputes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cross-merchant entity graph: identity -> device / address / instrument.

    Every node is a salted hash. No raw email, phone, address or instrument
    detail exists in this file, and no PAN exists anywhere in the system.
    """
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for d in disputes:
        for kind, edge, dst in (
            ("device", "shares_device", d["device_hash"]),
            ("address_geo", "shares_address", d["address_hash"]),
            ("instrument", "shares_instrument", d["instrument_hash"]),
        ):
            key = (d["identity_hash"], edge, dst)
            row = agg.setdefault(key, {
                "src": d["identity_hash"], "src_kind": "identity",
                "dst": dst, "dst_kind": kind, "edge": edge,
                "merchant_ids": set(), "dispute_count": 0,
                "first_seen": d["created_at"], "last_seen": d["created_at"],
            })
            row["merchant_ids"].add(d["merchant_id"])
            row["dispute_count"] += 1
            row["first_seen"] = min(row["first_seen"], d["created_at"])
            row["last_seen"] = max(row["last_seen"], d["created_at"])

    out = []
    for row in agg.values():
        row["merchant_ids"] = sorted(row["merchant_ids"])
        row["merchant_span"] = len(row["merchant_ids"])
        out.append(row)
    out.sort(key=lambda r: (r["src"], r["edge"], r["dst"]))
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def summarise(corpus: dict[str, Any], seed: int, salt: str, target: int) -> dict[str, Any]:
    disputes, merchants, groups = corpus["disputes"], corpus["merchants"], corpus["groups"]
    n = len(disputes)

    def share(pred) -> dict[str, Any]:
        c: dict[str, int] = {}
        for d in disputes:
            c[pred(d)] = c.get(pred(d), 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    by_split: dict[str, list[dict[str, Any]]] = {}
    for d in disputes:
        by_split.setdefault(d["split"], []).append(d)

    # Every way a constraint can fire, including field qualifiers. Those are
    # enforced at bind time rather than evaluated afterwards, so counting only
    # violated + unevaluated left email_channel_only - the most load-bearing
    # rule in the matrix - out of the corpus summary entirely.
    constraint_counts: dict[str, int] = {}
    for d in disputes:
        events = (
            [f"blocking:{c}" for c in d["violated_constraints"]]
            + [f"warn:{c}" for c in d["warnings"]]
            + d["unevaluated_constraints"]
            + [f"rejected:{r['constraint_id']}" for r in d["rejected_artifacts"]]
        )
        for c in events:
            constraint_counts[c] = constraint_counts.get(c, 0) + 1

    return {
        "seed": seed,
        "salt": salt,
        "target_disputes": target,
        "generated_at_corpus_start": CORPUS_START,
        "corpus_days": CORPUS_DAYS,
        "counts": {
            "disputes": n,
            "merchants": len(merchants),
            "groups": len(groups),
            "rings": sum(1 for g in groups if g["is_abusive"]),
            "decoys": sum(1 for g in groups if not g["is_abusive"]),
            "claimants": len({d["claimant_id"] for d in disputes}),
        },
        "splits": {
            s: {
                "disputes": len(rows),
                "share": round(len(rows) / n, 4),
                "merchants": sum(1 for m in merchants if m["split"] == s),
                "winnable_rate": round(sum(r["gt_winnable"] for r in rows) / len(rows), 4),
                "observed_win_rate": round(sum(r["observed_won"] for r in rows) / len(rows), 4),
            }
            for s, rows in sorted(by_split.items())
        },
        "rates": {
            "evidence_sufficient": round(sum(d["evidence_sufficient"] for d in disputes) / n, 4),
            "any_blocking_gap": round(sum(bool(d["blocking_gaps"]) for d in disputes) / n, 4),
            "merchant_at_fault": round(sum(d["gt_merchant_at_fault"] for d in disputes) / n, 4),
            "gt_winnable": round(sum(d["gt_winnable"] for d in disputes) / n, 4),
            "observed_won": round(sum(d["observed_won"] for d in disputes) / n, 4),
            "routed_to_human": round(
                sum(d["routing"] == "route_to_human" for d in disputes) / n, 4),
        },
        "constraint_events": dict(sorted(constraint_counts.items(), key=lambda kv: -kv[1])),
        "by_network": share(lambda d: d["network"]),
        "by_archetype": share(lambda d: d["merchant_archetype"]),
        "by_phase": share(lambda d: d["phase"]),
        "top_reason_codes": dict(list(share(lambda d: d["reason_code"]).items())[:12]),
        "issuer_noise": {
            "false_loss_rate": ISSUER_NOISE.false_loss_rate,
            "false_win_rate": ISSUER_NOISE.false_win_rate,
            "late_filing_penalty": ISSUER_NOISE.late_filing_penalty,
            "phase_escalation_penalty": ISSUER_NOISE.phase_escalation_penalty,
        },
        "economics": {
            "contest_cost_minor": ECONOMICS.contest_cost_minor,
            "rush_multiplier": ECONOMICS.rush_multiplier,
        },
        "split_ratios_requested": SPLIT_RATIOS,
        "violation_rates": VIOLATION_RATES,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="../corpus", help="output directory")
    ap.add_argument("--seed", type=int, default=20260904)
    ap.add_argument("--target-disputes", type=int, default=17500,
                    help="corpus scale. Changes how many disputes are drawn, "
                         "never any rate or distribution.")
    ap.add_argument("--salt", default="praman-corpus-v1",
                    help="hashing salt for entity ids. Part of the seed.")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    corpus = build_corpus(args.seed, args.target_disputes, args.salt)
    edges = build_entity_edges(corpus["disputes"])

    write_jsonl(out / "disputes.jsonl", corpus["disputes"])
    write_jsonl(out / "merchants.jsonl", corpus["merchants"])
    write_jsonl(out / "groups.jsonl", [
        {k: v for k, v in g.items() if k != "members"} | {"member_count": len(g["members"])}
        for g in corpus["groups"]
    ])
    write_jsonl(out / "entity_edges.jsonl", edges)

    summary = summarise(corpus, args.seed, args.salt, args.target_disputes)
    summary["counts"]["entity_edges"] = len(edges)
    with open(out / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)

    c = summary["counts"]
    print(f"corpus written to {out}")
    print(f"  {c['disputes']:,} disputes  {c['merchants']} merchants  "
          f"{c['rings']} rings  {c['decoys']} decoys  {c['entity_edges']:,} edges")
    for s, v in summary["splits"].items():
        print(f"  {s:12s} {v['disputes']:6,} disputes ({v['share']:.0%})  "
              f"{v['merchants']:2d} merchants  winnable {v['winnable_rate']:.3f}")
    print(f"  evidence sufficient {summary['rates']['evidence_sufficient']:.3f}  "
          f"blocking gap {summary['rates']['any_blocking_gap']:.3f}  "
          f"observed won {summary['rates']['observed_won']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
