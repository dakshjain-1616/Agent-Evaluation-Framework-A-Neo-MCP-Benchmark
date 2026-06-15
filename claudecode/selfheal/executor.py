"""The resilient executor — the heart of self-healing.

For a single step it runs the full recovery loop:

    run -> (on error) classify -> transient? -> repair args? -> backoff ->
    retry -> verify output -> record recovery path -> escalate if required

This is deliberately *not* a bare "retry N times then give up" loop. The action
taken after each failure is chosen from the failure's classification, arguments
are repaired between attempts when possible, successful output is verified, and
the entire recovery path is recorded as an incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import PipelineConfig
from .failures import Failure, FailureClass, FailureClassifier, HeuristicClassifier
from .observability import EventKind, Observability
from .repair import ArgumentRepairer, SchemaRepairer
from .tools import Tool, ToolRegistry
from .verification import AlwaysValid, OutputVerifier


class StepStatus(str, Enum):
    SUCCESS = "success"       # succeeded on the first attempt
    RECOVERED = "recovered"   # failed at least once, then self-healed
    ESCALATED = "escalated"   # could not be recovered; needs human/upstream attention


@dataclass
class StepResult:
    tool: str
    status: StepStatus
    value: Any = None
    attempts: int = 0
    final_args: dict[str, Any] = field(default_factory=dict)
    failure: Failure | None = None

    @property
    def ok(self) -> bool:
        return self.status in (StepStatus.SUCCESS, StepStatus.RECOVERED)


class ResilientExecutor:
    """Executes a single tool call with classification-driven recovery."""

    def __init__(
        self,
        registry: ToolRegistry,
        observability: Observability,
        config: PipelineConfig | None = None,
        classifier: FailureClassifier | None = None,
        repairer: ArgumentRepairer | None = None,
        verifier: OutputVerifier | None = None,
    ) -> None:
        self.registry = registry
        self.obs = observability
        self.config = config or PipelineConfig()
        self.classifier = classifier or HeuristicClassifier()
        self.repairer = repairer or SchemaRepairer()
        self.verifier = verifier or AlwaysValid()

    def execute(self, tool_name: str, args: dict[str, Any]) -> StepResult:
        tool = self.registry.get(tool_name)
        policy = self.config.retry_policy
        current_args = dict(args)
        last_failure: Failure | None = None
        had_failure = False

        for attempt in range(1, policy.max_attempts + 1):
            self._maybe_backoff(attempt, last_failure, tool_name)

            self.obs.metrics.attempts += 1
            self.obs.emit(EventKind.ATTEMPT_START, tool=tool_name, attempt=attempt,
                          data={"args": current_args})

            t0 = self.config.clock()
            try:
                value = tool.run(**current_args)
            except BaseException as exc:  # noqa: BLE001 - we classify everything
                self.obs.metrics.latencies.append(self.config.clock() - t0)
                failure = self.classifier.classify(exc, tool=tool_name, attempt=attempt)
                last_failure = failure
                had_failure = True
                self._on_failure(tool_name, failure)

                decision = self._decide(tool, current_args, failure, attempt)
                if decision.escalate:
                    return self._escalate(tool_name, attempt, current_args, failure)
                if decision.repaired_args is not None:
                    current_args = decision.repaired_args
                continue  # retry

            # No exception — but is the output actually good?
            self.obs.metrics.latencies.append(self.config.clock() - t0)
            verdict = self._verify(tool, current_args, value)
            if verdict is not None:
                # Verification failed -> synthesise a BAD_OUTPUT failure.
                last_failure = verdict
                had_failure = True
                self._on_failure(tool_name, verdict, verification=True)
                decision = self._decide(tool, current_args, verdict, attempt)
                if decision.escalate:
                    return self._escalate(tool_name, attempt, current_args, verdict)
                if decision.repaired_args is not None:
                    current_args = decision.repaired_args
                continue

            return self._succeed(tool_name, attempt, current_args, value, had_failure)

        # Attempts exhausted.
        assert last_failure is not None
        return self._escalate(tool_name, policy.max_attempts, current_args, last_failure,
                              reason="retries exhausted")

    # -- internals ---------------------------------------------------------

    @dataclass
    class _Decision:
        escalate: bool = False
        repaired_args: dict[str, Any] | None = None

    def _decide(self, tool: Tool, args: dict[str, Any], failure: Failure, attempt: int) -> "_Decision":
        """Pick the recovery action implied by the failure's classification."""
        fclass = failure.failure_class

        if fclass.terminal:
            return self._Decision(escalate=True)

        if fclass.repairable and self.config.enable_argument_repair:
            repaired = self.repairer.repair(tool, args, failure)
            if repaired is not None:
                self.obs.metrics.repairs += 1
                self.obs.emit(EventKind.REPAIR_APPLIED, tool=tool.name, attempt=attempt,
                              failure_class=fclass, data={"args": repaired})
                return self._Decision(repaired_args=repaired)
            self.obs.emit(EventKind.REPAIR_SKIPPED, tool=tool.name, attempt=attempt,
                          failure_class=fclass, message="no repair available")

        # Retry unchanged only if doing so could plausibly change the outcome.
        if fclass.retryable:
            return self._Decision()
        return self._Decision(escalate=True)

    def _maybe_backoff(self, attempt: int, last_failure: Failure | None, tool_name: str) -> None:
        if attempt <= 1 or last_failure is None:
            return
        if not last_failure.failure_class.needs_backoff:
            return
        delay = self.config.retry_policy.delay_for(attempt, self.config.rng)
        if delay > 0:
            self.obs.metrics.backoff_seconds += delay
            self.obs.emit(EventKind.BACKOFF, tool=tool_name, attempt=attempt,
                          failure_class=last_failure.failure_class,
                          data={"delay": round(delay, 6)})
            self.config.sleep_fn(delay)

    def _verify(self, tool: Tool, args: dict[str, Any], value: Any) -> Failure | None:
        if not self.config.enable_output_verification:
            return None
        result = self.verifier.verify(tool, args, value)
        if result.ok:
            return None
        return Failure(
            failure_class=FailureClass.BAD_OUTPUT,
            message=result.reason,
            tool=tool.name,
            attempt=0,
            metadata={"value": value},
        )

    def _on_failure(self, tool_name: str, failure: Failure, *, verification: bool = False) -> None:
        self.obs.incidents.ensure_open(tool_name)
        self.obs.metrics.record_failure(failure.failure_class)
        kind = EventKind.VERIFICATION_FAILED if verification else EventKind.ATTEMPT_FAILURE
        self.obs.emit(kind, tool=tool_name, attempt=failure.attempt,
                      failure_class=failure.failure_class, message=failure.message)
        self.obs.emit(EventKind.CLASSIFIED, tool=tool_name, attempt=failure.attempt,
                      failure_class=failure.failure_class,
                      data={"transient": failure.transient, "confidence": failure.confidence})

    def _succeed(self, tool_name: str, attempt: int, args: dict[str, Any],
                 value: Any, had_failure: bool) -> StepResult:
        self.obs.metrics.successes += 1
        if had_failure:
            self.obs.metrics.recoveries += 1
            self.obs.emit(EventKind.RECOVERED, tool=tool_name, attempt=attempt)
            self.obs.incidents.resolve(f"recovered after {attempt} attempt(s)")
            status = StepStatus.RECOVERED
        else:
            self.obs.emit(EventKind.ATTEMPT_SUCCESS, tool=tool_name, attempt=attempt)
            status = StepStatus.SUCCESS
        return StepResult(tool_name, status, value=value, attempts=attempt, final_args=args)

    def _escalate(self, tool_name: str, attempt: int, args: dict[str, Any],
                  failure: Failure, reason: str = "") -> StepResult:
        self.obs.metrics.escalations += 1
        msg = reason or failure.failure_class.value
        self.obs.emit(EventKind.ESCALATED, tool=tool_name, attempt=attempt,
                      failure_class=failure.failure_class, message=msg)
        self.obs.incidents.fail(failure, f"escalated: {msg}")
        return StepResult(tool_name, StepStatus.ESCALATED, attempts=attempt,
                          final_args=args, failure=failure)
