from __future__ import annotations

import pytest

from praman.evidence import ReasonCodeMatrix


@pytest.fixture(scope="session")
def matrix() -> ReasonCodeMatrix:
    return ReasonCodeMatrix.load()
