"""The agent contract, and the wrapper that makes partial failure the default.

Every agent is `async def run(case, budget_ms) -> AgentResult`. It must return
within budget, must return *something* (degraded is a valid answer), and must
never raise into the orchestrator. `guarded()` enforces all three from the
outside, so an agent cannot break the contract even by crashing.

Degradation is surfaced, never hidden. A silent partial result in a money system
is the failure mode that ends careers: the merchant sees a confident
recommendation built on half the evidence and has no way to know.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

Status = Literal["ok", "degraded", "failed", "timeout"]


@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: Status
    # Float, not int. These agents complete in tens of microseconds, and
    # truncating to whole milliseconds reported every one of them as 0.0 - a
    # latency table full of measured-looking zeros that measured nothing.
    latency_ms: float
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    errors: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status in ("ok", "degraded")


class Agent(Protocol):
    name: str

    async def run(self, case: Any, budget_ms: int) -> AgentResult: ...


async def guarded(
    agent: Agent, case: Any, budget_ms: int, clock: Callable[[], float] = time.perf_counter
) -> AgentResult:
    """Run an agent so that the orchestrator cannot be harmed by it.

    Three failure modes, three defined outcomes, no exceptions escaping:
      - overruns its budget      -> `timeout`
      - raises                   -> `failed`, with the exception recorded
      - returns the wrong type   -> `failed`, because a contract violation is a
                                    failure and not something to paper over
    """
    started = clock()

    def elapsed() -> float:
        return round((clock() - started) * 1000, 3)

    try:
        result = await asyncio.wait_for(agent.run(case, budget_ms), timeout=budget_ms / 1000)
    except TimeoutError:
        return AgentResult(agent.name, "timeout", elapsed(), confidence=0.0,
                           errors=(f"exceeded {budget_ms}ms budget",))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the whole point is to catch everything
        return AgentResult(agent.name, "failed", elapsed(), confidence=0.0,
                           errors=(f"{type(exc).__name__}: {exc}",))

    if not isinstance(result, AgentResult):
        return AgentResult(agent.name, "failed", elapsed(), confidence=0.0,
                           errors=(f"returned {type(result).__name__}, not AgentResult",))

    # Latency is stamped HERE, from the outside, not taken from the agent.
    # Every agent constructs its result with `latency_ms=0` because none of them
    # can honestly time themselves - they would be measuring their own body and
    # missing the await. A self-reported zero rendered in a latency table is a
    # measured-looking number that measures nothing.
    return replace(result, latency_ms=elapsed())


def deadline_budget(hours_remaining: float, agents: list[str]) -> dict[str, int]:
    """Per-agent budgets, tightened as the filing deadline approaches.

    Per-agent rather than one global timeout: a slow graph query must not be
    able to starve evidence retrieval, and it is evidence retrieval that decides
    whether a package can be assembled at all.
    """
    if hours_remaining <= 4:
        total = 2_000
    elif hours_remaining <= 24:
        total = 4_000
    elif hours_remaining <= 72:
        total = 6_000
    else:
        total = 8_000

    # Evidence retrieval is I/O-bound across several sources and is the one
    # agent whose absence blocks a package outright, so it gets the largest
    # share. Policy is deterministic and local, so it needs almost nothing.
    weights = {
        "evidence": 0.34, "network": 0.24, "precedent": 0.20,
        "merchant": 0.16, "policy": 0.06,
    }
    default = 1.0 / max(len(agents), 1)
    raw = {a: weights.get(a, default) for a in agents}
    scale = sum(raw.values()) or 1.0
    return {a: max(150, int(total * w / scale)) for a, w in raw.items()}
