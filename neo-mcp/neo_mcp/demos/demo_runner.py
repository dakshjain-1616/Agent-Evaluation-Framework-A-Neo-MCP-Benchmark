"""
E2E Demo Runner — demonstrates all recovery paths of the self-healing agent.

Run: python3 -m neo_mcp.demos.demo_runner

Expected output visible in terminal: For each failure type, the demo shows:
  → failure occurs
  → classification (TRANSIENT / PERMANENT_BAD_ARGS / etc.)
  → strategy applied (RETRY / REPAIR_AND_RETRY / ESCALATE / FAIL)
  → retry/recovery attempt
  → output verification
  → incident recorded

This exercises the Recovery State Machine: classify → strategy → repair/backoff → retry → verify.
"""

from __future__ import annotations

import asyncio
import random
import sys
from typing import Any, Dict

# Fix seed for deterministic demo
random.seed(42)

from neo_mcp.agent.orchestrator import SelfHealingAgent
from neo_mcp.core.models import RecoveryAction, Plan, Step
from neo_mcp.demos.demo_tools import (
    TOOL_INPUT_SCHEMAS,
    TOOL_OUTPUT_SCHEMAS,
    _reset_state,
    calculate,
    get_weather,
    query_database,
    send_email,
    validate_report,
)
from neo_mcp.executor.registry import ToolRegistry, ToolExecutor
from neo_mcp.observability.instrumentation import ConsoleInstrumentation
from neo_mcp.planners.fixed_planner import FixedPlanner
from neo_mcp.recovery.argument_repairer import NullArgumentRepairer
from neo_mcp.recovery.failure_classifier import RuleBasedFailureClassifier
from neo_mcp.recovery.orchestrator import RecoveryOrchestrator
from neo_mcp.recovery.output_verifier import SchemaOutputVerifier
from neo_mcp.recovery.strategies import (
    EscalateStrategy,
    ExponentialBackoffStrategy,
    FailStrategy,
    RepairAndRetryStrategy,
)


def setup_tools() -> ToolRegistry:
    """Register all demo tools with their schemas."""
    reg = ToolRegistry()
    reg.register(
        "get_weather",
        get_weather,
        input_schema=TOOL_INPUT_SCHEMAS["get_weather"],
        output_schema=TOOL_OUTPUT_SCHEMAS["get_weather"],
        description="Get weather for a city. May hit rate limits.",
    )
    reg.register(
        "query_database",
        query_database,
        input_schema=TOOL_INPUT_SCHEMAS["query_database"],
        output_schema=TOOL_OUTPUT_SCHEMAS["query_database"],
        description="Query database. Schema violations trigger argument repair.",
    )
    reg.register(
        "validate_report",
        validate_report,
        input_schema=TOOL_INPUT_SCHEMAS["validate_report"],
        output_schema=TOOL_OUTPUT_SCHEMAS["validate_report"],
        description="Validate a report. Output may fail schema check (demonstrates output-verification-fails-then-recovers).",
    )
    reg.register(
        "calculate",
        calculate,
        input_schema=TOOL_INPUT_SCHEMAS["calculate"],
        output_schema=TOOL_OUTPUT_SCHEMAS["calculate"],
        description="Evaluate a math expression. May randomly timeout.",
    )
    reg.register(
        "send_email",
        send_email,
        input_schema=TOOL_INPUT_SCHEMAS["send_email"],
        output_schema=TOOL_OUTPUT_SCHEMAS["send_email"],
        description="Send an email. Always works.",
    )
    return reg


def build_plan(goal: str) -> Plan:
    """Build a multi-step plan that exercises all recovery paths."""
    return Plan(
        goal=goal,
        steps=[
            Step(
                step_id="step_1",
                tool_name="get_weather",
                arguments={"city": "London"},
                description="Get weather for London",
                max_retries=3,
            ),
            Step(
                step_id="step_2",
                tool_name="get_weather",
                arguments={"city": "Paris"},
                description="Get weather for Paris",
                max_retries=3,
            ),
            Step(
                step_id="step_3",
                tool_name="get_weather",
                arguments={"city": "Tokyo"},
                description="Get weather for Tokyo (every 3rd call hits rate limit)",
                max_retries=3,
            ),
            Step(
                step_id="step_4",
                tool_name="query_database",
                arguments={"query": "SELECT * FROM users"},
                description="Query database (may trigger argument repair via schema violation)",
                max_retries=3,
            ),
            Step(
                step_id="step_5",
                tool_name="validate_report",
                arguments={"data": {"report_type": "quarterly"}},
                description="Validate a report (may trigger output-verification-fails-then-recovers)",
                max_retries=3,
            ),
            Step(
                step_id="step_6",
                tool_name="calculate",
                arguments={"expression": "42 * 2"},
                description="Calculate math (may timeout — transient retry)",
                max_retries=3,
            ),
            Step(
                step_id="step_7",
                tool_name="send_email",
                arguments={
                    "to": "admin@example.com",
                    "subject": "Demo complete",
                    "body": "All steps executed",
                },
                description="Send completion email (always works)",
                max_retries=1,
            ),
        ],
    )


async def run_demo() -> None:
    """Run the full E2E demo."""
    print("=" * 70)
    print("  NEO-MCP SELF-HEALING AGENT PLATFORM — E2E DEMO")
    print("  Recovery State Machine: Classify → Strategy → Repair/Backoff → Retry → Verify")
    print("=" * 70)
    print()

    # Reset flaky tool state
    _reset_state()

    # Setup components
    registry = setup_tools()
    executor = ToolExecutor(registry)
    instrumentation = ConsoleInstrumentation(verbose=True)

    classifier = RuleBasedFailureClassifier()

    strategies: Dict[RecoveryAction, Any] = {
        RecoveryAction.RETRY: ExponentialBackoffStrategy(
            base_delay=0.2, max_delay=2.0
        ),
        RecoveryAction.REPAIR_AND_RETRY: RepairAndRetryStrategy(
            NullArgumentRepairer()
        ),
        RecoveryAction.ESCALATE: EscalateStrategy(),
        RecoveryAction.FAIL: FailStrategy(),
    }

    output_verifier = SchemaOutputVerifier()

    recovery = RecoveryOrchestrator(
        classifier=classifier,
        strategies=strategies,
        executor=executor,
        output_verifier=output_verifier,
        instrumentation=instrumentation,
        max_attempts=3,
    )

    # Use FixedPlanner with known plan for deterministic demo
    goal = "Run the E2E demo exercising all recovery paths"
    plan = build_plan(goal)
    planner = FixedPlanner(plan)

    agent = SelfHealingAgent(
        planner=planner,
        executor=executor,
        recovery_orchestrator=recovery,
        instrumentation=instrumentation,
        output_verifier=output_verifier,
        output_schemas=TOOL_OUTPUT_SCHEMAS,
    )

    print(">>> AGENT STARTING <<<")
    print(f"Goal: {goal}")
    print(f"Plan: {len(plan.steps)} steps")
    print()

    result = await agent.run(goal, tool_descriptions=registry.get_descriptions())

    print()
    print("=" * 70)
    print("  EXECUTION SUMMARY")
    print("=" * 70)
    print()
    print(result.summary)
    print()

    # Print detailed incident report
    if result.incidents:
        print("─" * 50)
        print("  INCIDENT REPORT")
        print("─" * 50)
        for i, inc in enumerate(result.incidents, 1):
            print(f"\n  Incident #{i}: {inc['tool_name']}")
            print(f"    Error: {inc['original_error']}")
            print(
                f"    Classification: {inc['classification']['category']} → "
                f"{inc['classification']['action']}"
            )
            print(f"    Details: {inc['classification']['details']}")
            print(f"    Final Verdict: {inc['final_verdict']}")
            print(f"    Resolved: {inc['resolved']}")
            for attempt in inc["attempts"]:
                status = "✓" if attempt["success"] else "✗"
                print(
                    f"    Attempt #{attempt['number']}: {attempt['action']} "
                    f"({attempt['duration_ms']}ms) [{status}]"
                )
            print()

    print("=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)

    # Print metrics
    metrics = instrumentation.get_metrics_snapshot()
    print("\nMetrics:")
    for key, val in metrics.items():
        print(f"  {key}: {val}")


def main() -> None:
    """Entry point for the demo."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()