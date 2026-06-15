"""The self-healing pipeline.

Composes a :class:`PlanningEngine` with a :class:`ResilientExecutor` and
:class:`Observability`. The pipeline:

1. asks the planner for a plan,
2. executes each step with full call-level self-healing,
3. on a terminal (escalated) step, optionally asks the planner to *replan* with
   the failure in context (strategy-level self-healing), up to a budget, and
4. returns a structured :class:`PipelineResult` with per-step outcomes, the
   metrics snapshot, and the incident reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import PipelineConfig
from .executor import ResilientExecutor, StepResult, StepStatus
from .observability import EventKind, Observability
from .planning import PlanContext, PlanningEngine


class PipelineStatus(str, Enum):
    SUCCESS = "success"     # every step ok (some may have self-healed)
    PARTIAL = "partial"     # finished but at least one step needed escalation
    FAILED = "failed"       # a step escalated and could not be routed around


@dataclass
class PipelineResult:
    goal: str
    status: PipelineStatus
    steps: list[StepResult] = field(default_factory=list)
    replans: int = 0

    @property
    def value(self) -> Any:
        """The result of the final successful step, if any."""
        for step in reversed(self.steps):
            if step.ok:
                return step.value
        return None


class SelfHealingPipeline:
    def __init__(
        self,
        planner: PlanningEngine,
        executor: ResilientExecutor,
        observability: Observability,
        config: PipelineConfig | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.obs = observability
        self.config = config or executor.config

    def run(self, goal: str, context: dict[str, Any] | None = None) -> PipelineResult:
        results: dict[str, Any] = dict(context or {})
        step_results: list[StepResult] = []
        replans = 0
        last_failure = None

        plan_ctx = PlanContext(goal=goal, results=results)
        plan = self.planner.plan(plan_ctx)
        self.obs.emit(EventKind.PLAN_CREATED, message=goal,
                      data={"steps": [s.label() for s in plan.steps]})

        idx = 0
        while idx < len(plan.steps):
            step = plan.steps[idx]
            self.obs.emit(EventKind.STEP_START, tool=step.tool, message=step.label())

            result = self.executor.execute(step.tool, step.args)
            step_results.append(result)
            self.obs.emit(EventKind.STEP_DONE, tool=step.tool,
                          message=result.status.value)

            if result.ok:
                results[step.label()] = result.value
                idx += 1
                continue

            # Step escalated. Try to replan around it, if budget remains.
            last_failure = result.failure
            if replans < self.config.max_replans:
                replans += 1
                self.obs.emit(EventKind.REPLAN, tool=step.tool, message=str(last_failure),
                              data={"replan": replans})
                plan_ctx = PlanContext(goal=goal, results=results,
                                       last_failure=last_failure, replan_count=replans)
                plan = self.planner.plan(plan_ctx)
                idx = 0
                step_results.clear()  # fresh plan -> fresh step list
                continue

            # No replan budget left: stop here.
            return PipelineResult(goal, PipelineStatus.FAILED, step_results, replans)

        status = (
            PipelineStatus.SUCCESS
            if all(s.ok for s in step_results)
            else PipelineStatus.PARTIAL
        )
        return PipelineResult(goal, status, step_results, replans)
