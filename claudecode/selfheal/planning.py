"""Pluggable planning engines.

The pipeline depends only on the :class:`PlanningEngine` interface, so the
planner is swappable: a hard-coded plan for tests, a rule-based planner, or an
LLM-backed planner in production — none of which the recovery machinery needs to
know about. When a step escalates, the pipeline may ask the planner to *replan*
with the failure in context, enabling strategy-level self-healing on top of the
call-level recovery the executor provides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .failures import Failure


@dataclass(frozen=True)
class Step:
    """One unit of the plan: invoke ``tool`` with ``args``."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    name: str = ""

    def label(self) -> str:
        return self.name or self.tool


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)


@dataclass
class PlanContext:
    """Information available to the planner."""

    goal: str
    results: dict[str, Any] = field(default_factory=dict)
    last_failure: Failure | None = None
    replan_count: int = 0


class PlanningEngine(Protocol):
    def plan(self, context: PlanContext) -> Plan:
        ...


class StaticPlanner:
    """Returns a fixed list of steps, ignoring context. Useful for tests/demos."""

    def __init__(self, steps: list[Step]) -> None:
        self._steps = list(steps)

    def plan(self, context: PlanContext) -> Plan:
        return Plan(goal=context.goal, steps=list(self._steps))


class CallablePlanner:
    """Wraps a ``(PlanContext) -> list[Step]`` callable.

    This is the seam where an LLM planner plugs in: the callable can inspect the
    goal, prior results, and the last failure (when replanning) to produce the
    next set of steps.
    """

    def __init__(self, fn: Callable[[PlanContext], list[Step]]) -> None:
        self._fn = fn

    def plan(self, context: PlanContext) -> Plan:
        return Plan(goal=context.goal, steps=list(self._fn(context)))
