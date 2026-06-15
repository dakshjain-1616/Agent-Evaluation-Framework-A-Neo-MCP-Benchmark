"""Self-healing agent orchestrator — ties Planner + Executor + RecoveryOrchestrator + Instrumentation together."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from neo_mcp.core.interfaces import (
    Executor,
    Instrumentation,
    OutputVerifier,
    Planner,
)
from neo_mcp.core.models import Plan, Step, StepResult, Verdict
from neo_mcp.recovery.orchestrator import RecoveryOrchestrator


class AgentResult:
    """Result of running an agent through a goal.

    Wraps the execution output as an object with typed attributes
    for convenient access in tests and consumers.
    """

    def __init__(
        self,
        goal: str,
        step_results: List[StepResult],
        incidents: List[Dict[str, Any]],
        plan: Optional[Plan] = None,
        success: bool = True,
        summary: str = "",
    ) -> None:
        self.goal = goal
        self.plan = plan
        self.step_results = step_results
        self.incidents = incidents
        self.success = success and all(
            r.success for r in step_results if r.verdict != Verdict.SKIPPED
        )
        self.summary = summary


class SelfHealingAgent:
    """Autonomous self-healing agent.

    Runs a goal-driven plan with automatic failure recovery:

        1. Plan: Generate a plan from the goal
        2. Execute: Run each step in order
        3. Recover: If a step fails, run the recovery state machine
        4. Collect: Gather results and incident records
        5. Return: Final results and incidents

    If an OutputVerifier is provided, outputs of successful steps are also
    verified — if verification fails, it triggers the recovery flow
    (the 'output-verification-fails-then-recovers' path).
    """

    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        recovery_orchestrator: RecoveryOrchestrator,
        instrumentation: Optional[Instrumentation] = None,
        output_verifier: Optional[OutputVerifier] = None,
        output_schemas: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._recovery = recovery_orchestrator
        self._instrumentation = instrumentation
        self._output_verifier = output_verifier
        self._output_schemas = output_schemas or {}

    async def run(
        self,
        goal: str,
        tool_descriptions: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentResult:
        """Run the agent to achieve a goal.

        Args:
            goal: The objective to accomplish.
            tool_descriptions: Optional list of available tool descriptions
                for the planner.

        Returns:
            AgentResult with goal, plan, step_results, incidents, success, summary.
        """
        start_time = time.monotonic()
        self._log("INFO", "Agent starting", goal=goal)

        # 1. Plan
        plan = await self._planner.plan(
            goal=goal,
            tool_descriptions=tool_descriptions or [],
        )
        self._log("INFO", "Plan generated", steps=len(plan.steps))

        if self._instrumentation:
            self._instrumentation.increment("plans_generated")
            self._instrumentation.record_trace(
                "planning",
                "plan_created",
                duration_ms=0,
                goal=goal,
                num_steps=len(plan.steps),
            )

        # 2-3. Execute each step with recovery
        results: List[StepResult] = []
        incidents: List[Dict[str, Any]] = []
        all_successful = True
        escalated = False

        for step_idx, step in enumerate(plan.steps):
            if escalated:
                skipped_result = StepResult(
                    step=step,
                    success=False,
                    error="Skipped due to prior escalation",
                    verdict=Verdict.SKIPPED,
                )
                results.append(skipped_result)
                continue

            step_start = time.monotonic()
            self._log(
                "INFO",
                f"Executing step {step_idx + 1}/{len(plan.steps)}",
                step_id=step.step_id,
                tool=step.tool_name,
            )

            # Execute the step
            result = await self._executor.execute_step(step)

            output_verified = True
            if result.success:
                result.duration_ms = (time.monotonic() - step_start) * 1000

                # Verify output if output_verifier is provided
                if self._output_verifier and result.output is not None:
                    tool_schema = self._output_schemas.get(step.tool_name)
                    output_verified = self._output_verifier.verify(
                        result.output, step, tool_schema
                    )
                    if not output_verified:
                        self._log(
                            "WARN",
                            f"Step {step.step_id} output failed verification",
                            tool=step.tool_name,
                        )

            if result.success and output_verified:
                # Step succeeded and output is valid
                results.append(result)
                self._log(
                    "INFO",
                    f"Step {step.step_id} completed successfully",
                    tool=step.tool_name,
                    duration_ms=result.duration_ms,
                )
                if self._instrumentation:
                    self._instrumentation.increment("steps_succeeded")

            else:
                # Step execution failed OR output verification failed — run recovery
                recovery_error = (
                    result.error
                    if result.error
                    else f"Output verification failed for tool '{step.tool_name}'"
                )
                recovery_exception = (
                    result.exception_type
                    if result.exception_type
                    else "OutputVerificationError"
                )

                self._log(
                    "WARN",
                    f"Step {step.step_id} initiating recovery",
                    tool=step.tool_name,
                    error=recovery_error,
                )
                if self._instrumentation:
                    self._instrumentation.increment("steps_failed")

                incident = await self._recovery.recover(
                    step=step,
                    initial_error=recovery_error,
                    exception_type=recovery_exception,
                )

                # Build incident dict
                incident_dict = {
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "original_error": incident.original_error,
                    "classification": {
                        "category": (
                            incident.classification.category.value
                            if incident.classification
                            else None
                        ),
                        "action": (
                            incident.classification.action.value
                            if incident.classification
                            else None
                        ),
                        "details": (
                            incident.classification.details
                            if incident.classification
                            else None
                        ),
                    },
                    "attempts": [
                        {
                            "number": a.attempt_number,
                            "action": a.action.value,
                            "success": a.success,
                            "duration_ms": a.duration_ms,
                        }
                        for a in incident.attempts
                    ],
                    "final_verdict": incident.final_verdict.value,
                    "resolved": incident.resolved,
                }
                incidents.append(incident_dict)

                final_verdict = incident.final_verdict
                if final_verdict == Verdict.RECOVERED:
                    last_output = (
                        incident.attempts[-1].result.output
                        if incident.attempts and incident.attempts[-1].result
                        else None
                    )
                    result = StepResult(
                        step=step,
                        success=True,
                        output=last_output,
                        error=None,
                        verdict=Verdict.RECOVERED,
                        recovered=True,
                        attempts=len(incident.attempts),
                        duration_ms=(time.monotonic() - step_start) * 1000,
                    )
                    results.append(result)
                    if self._instrumentation:
                        self._instrumentation.increment("steps_recovered")

                elif final_verdict == Verdict.ESCALATED:
                    all_successful = False
                    escalated = True
                    result = StepResult(
                        step=step,
                        success=False,
                        error=incident.original_error,
                        verdict=Verdict.ESCALATED,
                        attempts=len(incident.attempts),
                        duration_ms=(time.monotonic() - step_start) * 1000,
                    )
                    results.append(result)

                else:  # FAILURE
                    all_successful = False
                    result = StepResult(
                        step=step,
                        success=False,
                        error=incident.original_error,
                        verdict=Verdict.FAILURE,
                        attempts=len(incident.attempts),
                        duration_ms=(time.monotonic() - step_start) * 1000,
                    )
                    results.append(result)

            if self._instrumentation:
                self._instrumentation.record_trace(
                    step.step_id,
                    "execute",
                    duration_ms=result.duration_ms,
                    tool=step.tool_name,
                    success=result.success,
                    verdict=result.verdict.value if result.verdict else "unknown",
                )

        total_time = (time.monotonic() - start_time) * 1000
        self._log(
            "INFO",
            "Agent run complete",
            goal=goal,
            total_duration_ms=round(total_time, 2),
            steps_completed=len(results),
            incidents=len(incidents),
            all_successful=all_successful,
        )

        summary = self._build_summary(results, incidents, total_time)

        return AgentResult(
            goal=goal,
            step_results=results,
            incidents=incidents,
            plan=plan,
            success=all_successful,
            summary=summary,
        )

    def _build_summary(
        self,
        results: List[StepResult],
        incidents: List[Dict[str, Any]],
        total_time_ms: float,
    ) -> str:
        """Build a human-readable execution summary."""
        total = len(results)
        succeeded = sum(1 for r in results if r.success)
        failed = total - succeeded
        recovered = sum(1 for r in results if r.recovered)
        skipped = sum(1 for r in results if r.verdict == Verdict.SKIPPED)

        lines = [
            f"Goal: {total} step(s) executed in {total_time_ms:.0f}ms",
            f"  ✓ {succeeded} succeeded ({recovered} recovered)",
            f"  ✗ {failed} failed ({skipped} skipped)",
        ]
        if incidents:
            lines.append("")
            lines.append("Incidents:")
            for inc in incidents:
                lines.append(
                    f"  [{inc['final_verdict']}] {inc['tool_name']}: "
                    f"{inc['classification']['category']} \u2192 "
                    f"{inc['classification']['action']} "
                    f"({inc['classification']['details'] or 'no details'})"
                )

        return "\n".join(lines)

    def _log(self, level: str, message: str, **context: Any) -> None:
        """Emit a log entry if instrumentation is available."""
        if self._instrumentation:
            self._instrumentation.log(level, message, **context)