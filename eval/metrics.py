"""Metric primitives shared by corpus validation and model evaluation."""

from __future__ import annotations

from collections.abc import Sequence


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Exact ROC AUC via the rank (Mann-Whitney U) identity, with tie handling.

    Written out rather than sampled. An earlier sampling implementation drew
    from the positive and negative pools in separate branches of a ternary and
    compared different draws, which returned ~0.5 for everything and nearly
    caused a wrong conclusion about corpus quality. This version is exact, so
    it cannot fail that way.

    Returns 0.5 when either class is empty - undefined, reported as chance.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels differ in length")
    pos = sum(1 for label in labels if label)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return 0.5

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        # Ties share the average of the ranks they span (1-indexed).
        shared = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1

    rank_sum = sum(r for r, label in zip(ranks, labels, strict=True) if label)
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def rupees(minor: float) -> str:
    """Indian digit grouping. A finance reader reads 31,27,069, not 3,127,069."""
    sign = "-" if minor < 0 else ""
    n = str(int(round(abs(minor) / 100)))
    if len(n) <= 3:
        body = n
    else:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        body = ",".join(parts) + "," + tail
    return f"{sign}Rs {body}"


def wilson(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Used because small denominators lie. Ring recall of 0 out of 4 is not
    "0.000" - it is consistent with any true recall below roughly a third, and
    reporting the point estimate as though it were precise overstates both the
    failure and our knowledge of it. Wilson rather than normal-approximation
    because the latter is degenerate at 0 and 1, which is exactly where these
    counts land.
    """
    if trials == 0:
        return (0.0, 1.0)
    phat = successes / trials
    denom = 1 + z * z / trials
    centre = (phat + z * z / (2 * trials)) / denom
    half = z / denom * ((phat * (1 - phat) / trials + z * z / (4 * trials * trials)) ** 0.5)
    return (max(0.0, centre - half), min(1.0, centre + half))
