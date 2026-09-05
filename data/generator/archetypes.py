"""Domain assumptions for the corpus generator.

Deliberately separated from the generation mechanics in `build.py` so a
skeptical reviewer can audit *what was assumed* without reading engine code.
Every number here is an assumption. None of it is observed data, and the
corpus is only as honest as this file is legible.

Run `python3 archetypes.py` to print the distributions for inspection.
"""

from __future__ import annotations

from dataclasses import dataclass

# Money is always minor units (paise) as int. Never floats, never rupees.
RUPEE = 100

# The evidence fields a merchant may or may not keep records for. `others` is
# modelled as a single hygiene probability covering all others.* types.
HYGIENE_FIELDS = (
    "shipping_proof",
    "billing_proof",
    "customer_communication",
    "proof_of_service",
    "refund_confirmation",
    "access_activity_log",
    "refund_cancellation_policy",
    "term_and_conditions",
    "explanation_letter",
    "cancellation_proof",
    "others",
)


@dataclass(frozen=True)
class MerchantArchetype:
    """A kind of business, with the record-keeping habits that come with it.

    `fulfilment_reliability` is the probability the merchant is *not* at fault
    when a grievance is raised against them. It is a fact about operations.
    `hygiene` is the probability a given document exists and is retrievable. It
    is a fact about record-keeping. The two are independent on purpose: a
    merchant can be entirely in the right and lose because nobody kept a signed
    delivery record.
    """

    name: str
    merchants: int
    monthly_orders: tuple[int, int]
    order_value_minor: tuple[int, int]  # lognormal median, spread as a percentage
    dispute_rate: tuple[float, float]
    fulfilment_reliability: tuple[float, float]
    signature_capture_rate: tuple[float, float]
    hygiene: dict[str, tuple[float, float]]
    support_channels: dict[str, float]
    reason_code_weights: dict[str, float]
    ocr_quality: tuple[float, float] = (0.88, 0.99)


def _hygiene(**kw: tuple[float, float]) -> dict[str, tuple[float, float]]:
    """Fill unspecified fields with a middling default so no field is silently
    absent from a merchant's profile."""
    base = dict.fromkeys(HYGIENE_FIELDS, (0.72, 0.92))
    base.update(kw)
    return base


MERCHANT_ARCHETYPES: tuple[MerchantArchetype, ...] = (
    MerchantArchetype(
        name="d2c_apparel",
        merchants=20,
        monthly_orders=(400, 4_000),
        order_value_minor=(1_800 * RUPEE, 65),
        dispute_rate=(0.004, 0.011),
        fulfilment_reliability=(0.82, 0.94),
        signature_capture_rate=(0.35, 0.70),
        hygiene=_hygiene(
            shipping_proof=(0.88, 0.98),
            customer_communication=(0.82, 0.95),
            refund_cancellation_policy=(0.75, 0.95),
            term_and_conditions=(0.80, 0.96),
            refund_confirmation=(0.82, 0.95),
            access_activity_log=(0.08, 0.25),
        ),
        support_channels={"email": 0.55, "whatsapp": 0.33, "phone": 0.12},
        reason_code_weights={
            "13.1": 0.26, "13.6": 0.14, "13.7": 0.11, "13.3": 0.09,
            "1064": 0.08, "1061": 0.06, "C08": 0.05, "RZP01": 0.08,
            "RZP04": 0.06, "4853": 0.04, "1101": 0.03,
        },
    ),
    MerchantArchetype(
        name="saas_subscription",
        merchants=20,
        monthly_orders=(80, 700),
        order_value_minor=(999 * RUPEE, 90),
        dispute_rate=(0.006, 0.016),
        fulfilment_reliability=(0.90, 0.98),
        signature_capture_rate=(0.0, 0.0),  # nothing is shipped
        hygiene=_hygiene(
            access_activity_log=(0.85, 0.98),
            refund_cancellation_policy=(0.80, 0.96),
            term_and_conditions=(0.85, 0.98),
            billing_proof=(0.85, 0.97),
            customer_communication=(0.75, 0.93),
            shipping_proof=(0.0, 0.0),
            proof_of_service=(0.70, 0.92),
        ),
        support_channels={"email": 0.86, "whatsapp": 0.08, "phone": 0.06},
        reason_code_weights={
            "13.2": 0.24, "4841": 0.18, "C28": 0.12, "RZP04": 0.12,
            "13.6": 0.10, "1061": 0.08, "RZP05": 0.08, "4853": 0.05,
            "C02": 0.03,
        },
    ),
    MerchantArchetype(
        name="food_delivery",
        merchants=20,
        monthly_orders=(2_000, 15_000),
        order_value_minor=(450 * RUPEE, 55),
        dispute_rate=(0.002, 0.006),
        fulfilment_reliability=(0.74, 0.90),
        signature_capture_rate=(0.02, 0.15),  # nobody signs for a biryani
        hygiene=_hygiene(
            shipping_proof=(0.78, 0.93),  # rider GPS ping, rarely a signature
            proof_of_service=(0.75, 0.92),
            customer_communication=(0.76, 0.92),
            refund_confirmation=(0.86, 0.96),
            refund_cancellation_policy=(0.76, 0.92),
            access_activity_log=(0.40, 0.70),
        ),
        support_channels={"email": 0.30, "whatsapp": 0.55, "phone": 0.15},
        reason_code_weights={
            "13.1": 0.20, "RZP01": 0.16, "1064": 0.12, "13.6": 0.11,
            "RZP04": 0.10, "1061": 0.08, "RZP06": 0.09, "C08": 0.05,
            "13.7": 0.05, "1101": 0.04,
        },
    ),
    MerchantArchetype(
        name="electronics",
        merchants=20,
        monthly_orders=(150, 1_800),
        order_value_minor=(15_000 * RUPEE, 80),
        dispute_rate=(0.005, 0.013),
        fulfilment_reliability=(0.80, 0.93),
        signature_capture_rate=(0.70, 0.95),  # high value, signature on delivery
        hygiene=_hygiene(
            shipping_proof=(0.85, 0.97),
            billing_proof=(0.80, 0.95),
            term_and_conditions=(0.75, 0.93),
            others=(0.72, 0.90),  # QC records, authenticity certificates
            customer_communication=(0.80, 0.94),
            refund_confirmation=(0.82, 0.95),
        ),
        support_channels={"email": 0.62, "whatsapp": 0.24, "phone": 0.14},
        reason_code_weights={
            "13.1": 0.16, "13.3": 0.15, "13.4": 0.09, "C32": 0.09,
            "C31": 0.07, "1062": 0.08, "13.6": 0.09, "C04": 0.06,
            "RZP01": 0.08, "4853": 0.06, "1101": 0.04, "13.5": 0.03,
        },
    ),
    MerchantArchetype(
        name="thin_records_smb",
        merchants=20,
        monthly_orders=(60, 900),
        order_value_minor=(2_500 * RUPEE, 95),
        dispute_rate=(0.010, 0.028),
        fulfilment_reliability=(0.65, 0.86),
        signature_capture_rate=(0.05, 0.30),
        # The archetype the product exists for: the evidence usually existed,
        # nobody kept it, and the dispute is lost by default.
        hygiene=_hygiene(
            shipping_proof=(0.52, 0.78),
            billing_proof=(0.62, 0.85),
            customer_communication=(0.60, 0.84),
            refund_cancellation_policy=(0.35, 0.65),
            term_and_conditions=(0.40, 0.70),
            access_activity_log=(0.10, 0.35),
            others=(0.25, 0.55),
        ),
        # Support lives on WhatsApp. Razorpay's documentation excludes WhatsApp
        # for RZP06/RZP00, so this is a real and silent way these merchants lose
        # disputes with paperwork attached.
        support_channels={"email": 0.18, "whatsapp": 0.70, "phone": 0.12},
        reason_code_weights={
            "RZP06": 0.20, "RZP00": 0.11, "RZP01": 0.13, "RZP05": 0.09,
            "13.1": 0.12, "RZP04": 0.09, "1064": 0.07, "13.6": 0.06,
            "1061": 0.05, "1101": 0.04, "M01": 0.04,
        },
        ocr_quality=(0.60, 0.95),  # phone photographs of printed slips
    ),
)


@dataclass(frozen=True)
class ClaimantArchetype:
    """Who raised the dispute, and how likely the merchant really is at fault.

    `merchant_fault_prior` is the entire reason evidence features cannot solve
    this task: it is invisible to record-keeping.
    """

    name: str
    share: float
    merchant_fault_prior: float
    disputes_per_claimant: tuple[int, int]


CLAIMANT_ARCHETYPES: tuple[ClaimantArchetype, ...] = (
    ClaimantArchetype("honest_grievance", 0.52, 0.88, (1, 2)),
    ClaimantArchetype("honest_confused", 0.23, 0.14, (1, 2)),
    ClaimantArchetype("opportunistic_solo", 0.19, 0.06, (1, 4)),
    ClaimantArchetype("ring_member", 0.06, 0.02, (2, 7)),
)


@dataclass(frozen=True)
class GroupProfile:
    """A cluster of claimants sharing entities.

    Rings and decoys are generated by *this same dataclass and the same code
    path* (ADR-006). They differ only in temporal concentration and dispute
    propensity. Building decoys differently would let a detector learn the
    artefact of the mechanism instead of the real discrimination.
    """

    name: str
    is_abusive: bool
    count: int
    members: tuple[int, int]
    merchant_span: tuple[int, int]
    shared_entities: tuple[str, ...]
    burst_days: tuple[int, int]        # window the disputes land in
    orders_per_member: tuple[int, int]  # how much each member actually buys
    dispute_propensity: tuple[float, float]  # disputes per member order

    def expected_disputes(self) -> float:
        """Rough disputes per group, for sanity-checking the profile by eye."""
        mid = lambda t: (t[0] + t[1]) / 2  # noqa: E731
        return mid(self.members) * mid(self.orders_per_member) * mid(self.dispute_propensity)


RING_PROFILES: tuple[GroupProfile, ...] = (
    GroupProfile(
        name="address_cluster", is_abusive=True, count=22,
        members=(4, 11), merchant_span=(3, 7), shared_entities=("address_geo",),
        burst_days=(9, 26), orders_per_member=(3, 9),
        dispute_propensity=(0.55, 0.85),
    ),
    GroupProfile(
        name="device_farm", is_abusive=True, count=20,
        members=(5, 14), merchant_span=(3, 8), shared_entities=("device",),
        burst_days=(6, 21), orders_per_member=(2, 7),
        dispute_propensity=(0.60, 0.90),
    ),
    GroupProfile(
        name="instrument_rotation", is_abusive=True, count=18,
        members=(3, 9), merchant_span=(2, 6),
        shared_entities=("instrument", "address_geo"),
        # The slow ring: patient, low-volume, and the hardest to catch.
        burst_days=(20, 80), orders_per_member=(2, 8),
        dispute_propensity=(0.22, 0.70),
    ),
)

DECOY_PROFILES: tuple[GroupProfile, ...] = (
    GroupProfile(
        name="household", is_abusive=False, count=34,
        members=(2, 5), merchant_span=(2, 5),
        shared_entities=("address_geo", "device"),
        burst_days=(70, 190), orders_per_member=(25, 90),
        dispute_propensity=(0.010, 0.085),
    ),
    GroupProfile(
        name="office_pantry", is_abusive=False, count=30,
        members=(4, 12), merchant_span=(2, 6), shared_entities=("address_geo",),
        burst_days=(100, 185), orders_per_member=(20, 75),
        dispute_propensity=(0.008, 0.040),
    ),
    GroupProfile(
        name="shared_device_pg", is_abusive=False, count=26,
        members=(3, 9), merchant_span=(2, 5), shared_entities=("device",),
        # The dispute-prone shared address: a decoy that looks like a ring.
        burst_days=(40, 150), orders_per_member=(30, 100),
        dispute_propensity=(0.020, 0.140),
    ),
)


@dataclass(frozen=True)
class IssuerNoise:
    """The gap between what should happen and what the merchant is told.

    Training on noiseless ground truth produces a model that is confidently
    wrong and a calibration curve that flatters the system (ADR-007). This is
    what caps achievable AUC, and that ceiling is a feature: a model reporting
    above it has a leak.
    """

    false_loss_rate: float = 0.14   # winnable case, lost anyway
    false_win_rate: float = 0.05    # unwinnable case, won anyway
    late_filing_penalty: float = 0.22   # filed inside the last 10% of the window
    phase_escalation_penalty: float = 0.15  # pre-arbitration and beyond


@dataclass(frozen=True)
class Economics:
    """Contest cost is a merchant input, not a law of nature. The economics are
    only as good as this number, so it is configurable everywhere it is used."""

    contest_cost_minor: int = 350 * RUPEE
    rush_multiplier: float = 1.6        # contesting at T-4h costs more than T-9d
    rush_window_hours: int = 24


ISSUER_NOISE = IssuerNoise()
ECONOMICS = Economics()

# Corpus window. Static by design; no temporal drift is modelled, and that is a
# stated limit rather than an oversight.
CORPUS_START = "2026-01-05"
CORPUS_DAYS = 180

SPLIT_RATIOS: dict[str, float] = {"train": 0.60, "calibration": 0.15, "test": 0.25}

PHASE_WEIGHTS: dict[str, float] = {
    "chargeback": 0.72,
    "pre_arbitration": 0.21,
    "arbitration": 0.07,
}

RESPOND_BY_DAYS: tuple[int, int] = (7, 21)


def _fmt_range(lo: float, hi: float) -> str:
    return f"{lo:.2f}-{hi:.2f}" if hi <= 1 else f"{lo:,.0f}-{hi:,.0f}"


def main() -> None:
    """Print the assumptions for inspection. `make validate` runs this."""
    print("=" * 78)
    print("MERCHANT ARCHETYPES  (all values assumed, none observed)")
    print("=" * 78)
    total_merchants = sum(a.merchants for a in MERCHANT_ARCHETYPES)
    for a in MERCHANT_ARCHETYPES:
        print(f"\n  {a.name}  x{a.merchants}")
        print(f"    monthly orders     {_fmt_range(*a.monthly_orders)}")
        print(f"    order value        Rs {a.order_value_minor[0] // RUPEE:,} median, "
              f"{a.order_value_minor[1]}% spread")
        print(f"    dispute rate       {_fmt_range(*a.dispute_rate)}")
        print(f"    fulfilment reliab. {_fmt_range(*a.fulfilment_reliability)}")
        print(f"    signature capture  {_fmt_range(*a.signature_capture_rate)}")
        print("    support channels   " + ", ".join(
            f"{k} {v:.0%}" for k, v in a.support_channels.items()))
        weak = sorted(a.hygiene.items(), key=lambda kv: kv[1][1])[:3]
        print("    weakest records    " + ", ".join(f"{k} {_fmt_range(*v)}" for k, v in weak))
        s = sum(a.reason_code_weights.values())
        assert abs(s - 1.0) < 1e-9, f"{a.name} reason weights sum to {s}"
        print(f"    reason codes       {len(a.reason_code_weights)} codes, weights sum {s:.3f}")
    print(f"\n  total merchants: {total_merchants}")

    print("\n" + "=" * 78)
    print("CLAIMANT ARCHETYPES")
    print("=" * 78)
    share = sum(c.share for c in CLAIMANT_ARCHETYPES)
    for c in CLAIMANT_ARCHETYPES:
        print(f"  {c.name:20s} share {c.share:.0%}   P(merchant at fault) {c.merchant_fault_prior:.2f}")
    assert abs(share - 1.0) < 1e-9, f"claimant shares sum to {share}"
    print(f"  shares sum {share:.3f}")

    print("\n" + "=" * 78)
    print("GROUPS  (rings and decoys share one code path - ADR-006)")
    print("=" * 78)
    for label, profiles in (("RING ", RING_PROFILES), ("DECOY", DECOY_PROFILES)):
        for p in profiles:
            per_day = p.expected_disputes() / ((p.burst_days[0] + p.burst_days[1]) / 2)
            print(f"  {label} {p.name:18s} x{p.count:3d}  members {_fmt_range(*p.members)}  "
                  f"burst {p.burst_days[0]}-{p.burst_days[1]}d  "
                  f"propensity {_fmt_range(*p.dispute_propensity)}  "
                  f"~{p.expected_disputes():.0f} disputes ({per_day:.2f}/day)")
    print(f"\n  rings {sum(p.count for p in RING_PROFILES)}  "
          f"decoys {sum(p.count for p in DECOY_PROFILES)}")
    print("\n  Burst windows overlap between rings and decoys by design. A slow ring "
          "\n  and a dispute-prone household are genuinely hard to separate, and that "
          "\n  overlap is where ring precision dies. It is not designed away.")

    print("\n" + "=" * 78)
    print("ISSUER NOISE AND ECONOMICS")
    print("=" * 78)
    print(f"  false loss on winnable   {ISSUER_NOISE.false_loss_rate:.0%}")
    print(f"  false win on unwinnable  {ISSUER_NOISE.false_win_rate:.0%}")
    print(f"  late filing penalty      {ISSUER_NOISE.late_filing_penalty:.0%}")
    print(f"  phase escalation penalty {ISSUER_NOISE.phase_escalation_penalty:.0%}")
    print(f"  contest cost             Rs {ECONOMICS.contest_cost_minor // RUPEE}")
    print("  split ratios             " + ", ".join(f"{k} {v:.0%}" for k, v in SPLIT_RATIOS.items()))
    print("\n  All of the above are assumptions. See data/README.md for what is real.")


if __name__ == "__main__":
    main()
