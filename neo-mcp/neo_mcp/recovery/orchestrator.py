"""Recovery orchestrator — state machine tying classifier → strategy → repair → retry → verify."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from neo_mcp.core.interfaces import (
    Executor,
    FailureClassifier,
    Instrumentation,
    OutputVerifier,
    RecoveryStrategy,
)
from neo_mcp.core.models import (
    FailureCategory,
    IncidentRecord,
    RecoveryAction,
    RecoveryAttempt,
    Step,
    StepResult,
    Verdict,
)


class RecoveryOrchestrator:
    """Implements the recovery state machine.

    Flow for a failed step:
        1. Classify the failure (FailureClassifier)
        2. Select strategy (based on RecoveryAction)
        3. Apply strategy (backoff/repair/escalate/fail)
        4. If strategy returns modified step → retry via Executor
        5. Verify output (OutputVerifier)
        6. If still failing → repeat or escalate
        7. Record incident
    """

    def __init__(
        self,
        classifier: FailureClassifier,
        strategies: Dict[RecoveryAction, RecoveryStrategy],
        executor: Executor,
        output_verifier: OutputVerifier,
        instrumentation: Optional[Instrumentation] = None,
        max_attempts: int = 3,
    ) -> None:
        self._classifier = classifier
        self._strategies = strategies
        self._executor = executor
        self._output_verifier = output_verifier
        self._instrumentation = instrumentation
        self._max_attempts = max_attempts

    async def recover(
        self,
        step: Step,
        initial_error: str,
        exception_type: Optional[str] = None,
        tool_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> IncidentRecord:
        """Run the full recovery state machine for a failed step.

        Args:
            step: The step that failed.
            initial_error: The error message from the failed execution.
            exception_type: Optional fully-qualified exception type.
            tool_schema: Optional input schema for the tool.
            output_schema: Optional output schema for verification.

        Returns:
            An IncidentRecord with the full recovery chain.
        """
        incident = IncidentRecord(
            step=step,
            original_error=initial_error,
        )

        # 1. Classify
        classification = self._classifier.classify(
            error_message=initial_error,
            exception_type=exception_type,
        )
        incident.classification = classification

        self._log(
            "INFO",
            "Failure classified",
            step_id=step.step_id,
            category=classification.category.value,
            action=classification.action.value,
            details=classification.details,
        )

        # 2-6. Recovery loop
        current_step = step
        current_error = initial_error
        current_exc_type = exception_type

        for attempt_num in range(1, self._max_attempts + 1):
            # 2. Select strategy
            strategy = self._strategies.get(classification.action)
            if strategy is None:
                # No strategy for this action — fall through to fail
                self._log(
                    "WARN",
                    f"No strategy registered for action {classification.action.value}",
                    step_id=step.step_id,
                )
                attempt = RecoveryAttempt(
                    attempt_number=attempt_num,
                    action=RecoveryAction.FAIL,
                    success=False,
                )
                incident.attempts.append(attempt)
                break

            self._log(
                "INFO",
                f"Applying recovery strategy: {strategy.__class__.__name__}",
                step_id=step.step_id,
                attempt=attempt_num,
            )

            # 3. Apply strategy
            attempt_start = time.monotonic()
            before_state = {
                "args": dict(current_step.arguments),
                "error": current_error,
            }

            result_step = await strategy.apply(
                step=current_step,
                error_message=current_error,
                attempt_number=attempt_num,
                tool_schema=tool_schema,
            )

            attempt_duration = (time.monotonic() - attempt_start) * 1000

            after_state = {
                "args": dict(result_step.arguments) if result_step else {},
            }

            # 4. If strategy returned None → no recovery possible
            if result_step is None:
                attempt = RecoveryAttempt(
                    attempt_number=attempt_num,
                    action=strategy.get_action(),
                    before_state=before_state,
                    after_state=after_state,
                    duration_ms=round(attempt_duration, 2),
                    success=False,
                )
                incident.attempts.append(attempt)
                break

            # 5. Retry via executor
            retry_start = time.monotonic()
            result = await self._executor.execute_step(result_step)
            retry_duration = (time.monotonic() - retry_start) * 1000

            attempt = RecoveryAttempt(
                attempt_number=attempt_num,
                action=strategy.get_action(),
                before_state=before_state,
                after_state=after_state,
                duration_ms=round(attempt_duration + retry_duration, 2),
                result=result,
                success=result.success,
            )

            if result.success:
                # 6. Verify output
                verified = self._output_verifier.verify(
                    output=result.output,
                    step=result_step,
                    output_schema=output_schema,
                )

                if verified:
                    # RECOVERED!
                    incident.final_verdict = Verdict.RECOVERED
                    incident.resolved = True
                    attempt.success = True
                    incident.attempts.append(attempt)
                    self._log(
                        "INFO",
                        "Recovery successful — output verified",
                        step_id=step.step_id,
                        attempts=attempt_num,
                    )
                    return incident
                else:
                    self._log(
                        "WARN",
                        "Output verification failed — retrying",
                        step_id=step.step_id,
                        attempt=attempt_num,
                    )
                    current_error = f"Output validation failed for {result_step.tool_name}"
                    current_exc_type = None
                    incident.attempts.append(attempt)
                    # Continue loop to retry
                    continue
            else:
                # Retry failed — update error info and continue loop
                current_error = result.error or current_error
                current_exc_type = result.exception_type or current_exc_type
                incident.attempts.append(attempt)

                self._log(
                    "WARN",
                    f"Retry attempt {attempt_num} failed",
                    step_id=step.step_id,
                    error=current_error,
                )
                # Re-classify the new error for next iteration
                classification = self._classifier.classify(
                    error_message=current_error,
                    exception_type=current_exc_type,
                )
                continue

        # All attempts exhausted — final verdict
        if incident.attempts:
            last_action = incident.attempts[-1].action
            if last_action == RecoveryAction.ESCALATE:
                incident.final_verdict = Verdict.ESCALATED
            elif last_action == RecoveryAction.FAIL:
                incident.final_verdict = Verdict.FAILURE
            else:
                incident.final_verdict = Verdict.FAILURE
        else:
            incident.final_verdict = Verdict.FAILURE

        self._log(
            "WARN",
            "Recovery exhausted — step failed",
            step_id=step.step_id,
            verdict=incident.final_verdict.value,
            attempts=len(incident.attempts),
        )

        return incident

    def _log(self, level: str, message: str, **context: Any) -> None:
        """Emit a log entry if instrumentation is available."""
        if self._instrumentation:
            self._instrumentation.log(level, message, **context)