"""The expected-cost decision rule.

    Let  A = disputed amount
         C = cost to contest (ops time + representment overhead)
         p = calibrated P(win | contest)

      EV(contest) = p*A - C     win: keep A. lose: keep nothing. always pay C.
      EV(accept)  = 0           the money is already debited

      Contest  <=>  p*A > C  <=>  p > C/A

The optimal threshold is a *function of the disputed amount*, not a constant.
At C = Rs 350, a Rs 500 dispute needs p > 0.70 to be worth contesting; a
Rs 50,000 dispute needs only p > 0.007. Thresholding at 0.5 gets both wrong in
opposite directions.

No model runs in this file. It is arithmetic over a calibrated probability, and
that is the whole point: the language model drafts prose, and a five-line
inequality decides whether a merchant spends money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Action = Literal["contest", "accept"]

DEFAULT_CONTEST_COST_MINOR = 35_000  # Rs 350. A merchant input, not a constant.


@dataclass(frozen=True)
class Decision:
    action: Action
    p_win: float
    amount_minor: int
    cost_minor: int
    break_even_p: float
    expected_value_minor: int
    rationale: str
    overrides: tuple[str, ...] = field(default_factory=tuple)


def break_even(amount_minor: int, cost_minor: int = DEFAULT_CONTEST_COST_MINOR) -> float:
    """C/A - the probability above which contesting pays for itself.

    Capped at 1.0: a dispute worth less than the cost of contesting it can never
    be worth contesting, however certain the win.
    """
    if amount_minor <= 0:
        return 1.0
    return min(1.0, cost_minor / amount_minor)


def expected_value(p_win: float, amount_minor: int, cost_minor: int) -> int:
    """EV of contesting, in minor units. Accepting is the zero baseline."""
    return int(round(p_win * amount_minor - cost_minor))


def rupees(minor: float) -> str:
    """Indian digit grouping - a finance reader reads 18,400, not 18400."""
    sign = "-" if minor < 0 else ""
    n = str(int(round(abs(minor) / 100)))
    if len(n) <= 3:
        return f"{sign}Rs {n}"
    head, tail = n[:-3], n[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"{sign}Rs {','.join(parts)},{tail}"


def decide(
    p_win: float,
    amount_minor: int,
    cost_minor: int = DEFAULT_CONTEST_COST_MINOR,
    *,
    evidence_sufficient: bool = True,
    blocking_gaps: tuple[str, ...] = (),
    comparable: tuple[int, int] | None = None,
    ring: str = "",
) -> Decision:
    """Contest or accept, and say why in language a merchant can check.

    The rationale is templated from the decision inputs. Nothing in it is
    written by a model, and every number in it is traceable to a source.
    """
    threshold = break_even(amount_minor, cost_minor)
    ev = expected_value(p_win, amount_minor, cost_minor)
    overrides: list[str] = []

    # A package that cannot be assembled cannot be filed, whatever the odds say.
    # This is not a probability judgement, it is a fact about record-keeping.
    if not evidence_sufficient:
        action: Action = "accept"
        overrides.append("evidence_insufficient")
    else:
        action = "contest" if p_win > threshold else "accept"

    parts: list[str] = []
    if action == "contest":
        parts.append("Contest.")
    else:
        parts.append("Accept.")

    if not evidence_sufficient:
        gaps = "; ".join(blocking_gaps) if blocking_gaps else "required evidence is missing"
        parts.append(f"The package cannot be assembled: {gaps}")
        parts.append(
            "Contesting without the required evidence spends "
            f"{rupees(cost_minor)} to lose the same {rupees(amount_minor)}."
        )
    else:
        if comparable:
            won, total = comparable
            parts.append(f"Comparable cases: {won} of {total} won.")
        parts.append(f"P(win) {p_win:.2f}, calibrated.")
        parts.append(
            f"At {rupees(amount_minor)} disputed against {rupees(cost_minor)} "
            f"contest cost, the break-even probability is {threshold:.3f}."
        )
        if action == "contest":
            parts.append(f"Expected value of contesting: {rupees(ev)}.")
        else:
            parts.append(
                f"Below break-even, so contesting loses {rupees(-ev)} on average."
            )
    if ring:
        parts.append(f"Network: {ring}")

    return Decision(
        action=action,
        p_win=round(p_win, 6),
        amount_minor=amount_minor,
        cost_minor=cost_minor,
        break_even_p=round(threshold, 6),
        expected_value_minor=ev,
        rationale=" ".join(parts),
        overrides=tuple(overrides),
    )
