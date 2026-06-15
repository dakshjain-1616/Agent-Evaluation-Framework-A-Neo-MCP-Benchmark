"""selfheal — a self-healing AI pipeline.

Detect failures, classify them, repair arguments, recover with the right
strategy, verify outputs, and record every incident — with observability and
pluggable planning built in from day one.

Quick start::

    from selfheal import (build_pipeline, FunctionTool, ArgSpec, Step,
                          StaticPlanner, SelfHealingPipeline)

    planner = StaticPlanner([Step("greet", {"name": "ada"})])
    _, registry, obs = build_pipeline()
    registry.register(FunctionTool("greet", lambda name: f"hi {name}",
                                   schema={"name": ArgSpec(str)}))
    pipeline, registry, obs = build_pipeline(planner)
    registry.register(FunctionTool("greet", lambda name: f"hi {name}",
                                   schema={"name": ArgSpec(str)}))
    result = pipeline.run("greet ada")
"""

from __future__ import annotations

from .config import PipelineConfig, RetryPolicy
from .executor import ResilientExecutor, StepResult, StepStatus
from .failures import (
    Failure,
    FailureClass,
    HeuristicClassifier,
    InvalidArgumentError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ResourceExhaustedError,
    ToolError,
    TransientError,
    UnavailableError,
)
from .observability import (
    Event,
    EventKind,
    InMemorySink,
    LoggingSink,
    Metrics,
    MultiSink,
    Observability,
)
from .pipeline import PipelineResult, PipelineStatus, SelfHealingPipeline
from .planning import (
    CallablePlanner,
    Plan,
    PlanContext,
    PlanningEngine,
    StaticPlanner,
    Step,
)
from .repair import ArgumentRepairer, SchemaRepairer
from .tools import ArgSpec, FunctionTool, Tool, ToolRegistry
from .verification import (
    AlwaysValid,
    NonEmptyVerifier,
    OutputVerifier,
    PredicateVerifier,
    VerificationResult,
)

__all__ = [
    "PipelineConfig", "RetryPolicy",
    "ResilientExecutor", "StepResult", "StepStatus",
    "Failure", "FailureClass", "HeuristicClassifier",
    "ToolError", "TransientError", "RateLimitError", "InvalidArgumentError",
    "ResourceExhaustedError", "NotFoundError", "PermissionDeniedError", "UnavailableError",
    "Event", "EventKind", "InMemorySink", "LoggingSink", "Metrics", "MultiSink", "Observability",
    "PipelineResult", "PipelineStatus", "SelfHealingPipeline",
    "CallablePlanner", "Plan", "PlanContext", "PlanningEngine", "StaticPlanner", "Step",
    "ArgumentRepairer", "SchemaRepairer",
    "ArgSpec", "FunctionTool", "Tool", "ToolRegistry",
    "AlwaysValid", "NonEmptyVerifier", "OutputVerifier", "PredicateVerifier", "VerificationResult",
    "build_pipeline",
]


def build_pipeline(
    planner: "PlanningEngine | None" = None,
    *,
    config: PipelineConfig | None = None,
    verifier: "OutputVerifier | None" = None,
    sink=None,
) -> "tuple[SelfHealingPipeline | None, ToolRegistry, Observability]":
    """Wire up the standard components.

    If ``planner`` is ``None`` the returned pipeline slot is ``None`` and callers
    can build their own once the planner is known; the registry and observability
    are always returned so tools can be registered first.
    """
    config = config or PipelineConfig()
    registry = ToolRegistry()
    obs = Observability(sink=sink, clock=config.clock)
    executor = ResilientExecutor(registry, obs, config=config, verifier=verifier)
    pipeline = (
        SelfHealingPipeline(planner, executor, obs, config=config)
        if planner is not None
        else None
    )
    return pipeline, registry, obs
