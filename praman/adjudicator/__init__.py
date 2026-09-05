"""Win probability, calibration, and the expected-cost decision rule.

The contest/accept decision is a deterministic inequality over a calibrated
probability. No model decides anything here; the model supplies `p` and
arithmetic does the rest.
"""

from .features import FeatureSpec, LeakageError, extract, guard, labels, matrix, spec
from .rule import Decision, break_even, decide, expected_value

__all__ = [
    "Decision",
    "FeatureSpec",
    "LeakageError",
    "break_even",
    "decide",
    "expected_value",
    "extract",
    "guard",
    "labels",
    "matrix",
    "spec",
]
