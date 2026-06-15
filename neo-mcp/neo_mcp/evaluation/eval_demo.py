"""E2E evaluation demo — runs SelfHealingAgent with an in-memory dataset,
scores results, detects regressions, and demonstrates the review queue.

Usage:
    source venv/bin/activate && python -m neo_mcp.evaluation.eval_demo

First run establishes baseline (all pass).
Second run injects degradation (get_weather tool modified) showing regression caught.
"""

from __future__ import annotations

import asyncio
import random
import tempfile
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
from neo_mcp.evaluation.datasets import EvaluationCase, InMemoryDataset
from neo_mcp.evaluation.eval_instrumentation import EvalInstrumentation
from neo_mcp.evaluation.regression import (
    JsonBaselineStore,
    RegressionDetector,
    RegressionVerdict,
)
from neo_mcp.evaluation.review import InMemoryReviewQueue, ReviewEntry, ReviewStatus
from neo_mcp.evaluation.runner import EvaluationRunner
from neo_mcp.evaluation.scoring import (
    ExactMatchMetric,
    LatencyMetric,
    RecoveryCountMetric,
    ScoreAggregator,
    SuccessRateMetric,
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
        description="Get weather for a city.",
    )
    reg.register(
        "query_database",
        query_database,
        input_schema=TOOL_INPUT_SCHEMAS["query_database"],
        output_schema=TOOL_OUTPUT_SCHEMAS["query_database"],
        description="Query database.",
    )
    reg.register(
        "validate_report",
        validate_report,
        input_schema=TOOL_INPUT_SCHEMAS["validate_report"],
        output_schema=TOOL_OUTPUT_SCHEMAS["validate_report"],
        description="Validate a report.",
    )
    reg.register(
        "calculate",
        calculate,
        input_schema=TOOL_INPUT_SCHEMAS["calculate"],
        output_schema=TOOL_OUTPUT_SCHEMAS["calculate"],
        description="Evaluate a math expression.",
    )
    reg.register(
        "send_email",
        send_email,
        input_schema=TOOL_INPUT_SCHEMAS["send_email"],
        output_schema=TOOL_OUTPUT_SCHEMAS["send_email"],
        description="Send an email.",
    )
    return reg


def create_dataset() -> InMemoryDataset:
    """Create an in-memory dataset with evaluation cases."""
    cases = [
        EvaluationCase(
            case_id="weather_london",
            goal="Get the weather for London",
            expected_output="Weather in London: 15°C, partly cloudy",
            metadata={"city": "London", "tool": "get_weather"},
        ),
        EvaluationCase(
            case_id="weather_paris",
            goal="Get the weather for Paris",
            expected_output="Weather in Paris: 18°C, partly cloudy",
            metadata={"city": "Paris", "tool": "get_weather"},
        ),
        EvaluationCase(
            case_id="calculate_twice",
            goal="Calculate 42 * 2",
            expected_output="84.0",
            metadata={"expression": "42 * 2", "tool": "calculate"},
        ),
    ]
    return InMemoryDataset(cases=cases, version="1.0.0")


def build_plan_for_case(case: EvaluationCase) -> Plan:
    """Build a FixedPlanner plan appropriate for each evaluation case."""
    if case.case_id == "weather_london":
        return Plan(
            goal=case.goal,
            steps=[
                Step(
                    step_id="get_weather",
                    tool_name="get_weather",
                    arguments={"city": "London"},
                    description="Get London weather",
                    max_retries=3,
                ),
                Step(
                    step_id="send_email",
                    tool_name="send_email",
                    arguments={
                        "to": "demo@example.com",
                        "subject": "London weather complete",
                        "body": "Weather data retrieved",
                    },
                    description="Send notification",
                    max_retries=1,
                ),
            ],
        )
    elif case.case_id == "weather_paris":
        return Plan(
            goal=case.goal,
            steps=[
                Step(
                    step_id="get_weather",
                    tool_name="get_weather",
                    arguments={"city": "Paris"},
                    description="Get Paris weather",
                    max_retries=3,
                ),
                Step(
                    step_id="send_email",
                    tool_name="send_email",
                    arguments={
                        "to": "demo@example.com",
                        "subject": "Paris weather complete",
                        "body": "Weather data retrieved",
                    },
                    description="Send notification",
                    max_retries=1,
                ),
            ],
        )
    else:  # calculate_twice
        return Plan(
            goal=case.goal,
            steps=[
                Step(
                    step_id="calculate",
                    tool_name="calculate",
                    arguments={"expression": "42 * 2"},
                    description="Calculate 42 * 2",
                    max_retries=3,
                ),
                Step(
                    step_id="send_email",
                    tool_name="send_email",
                    arguments={
                        "to": "demo@example.com",
                        "subject": "Calculation complete",
                        "body": "Calculation done",
                    },
                    description="Send notification",
                    max_retries=1,
                ),
            ],
        )


def create_agent(registry: ToolRegistry) -> SelfHealingAgent:
    """Create a SelfHealingAgent with proper recovery setup."""
    executor = ToolExecutor(registry)
    instrumentation = ConsoleInstrumentation(verbose=False)
    classifier = RuleBasedFailureClassifier()

    strategies: Dict[RecoveryAction, Any] = {
        RecoveryAction.RETRY: ExponentialBackoffStrategy(
            base_delay=0.05, max_delay=0.5
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

    return SelfHealingAgent(
        planner=FixedPlanner(Plan(goal="dummy", steps=[])),  # Will be overridden per-case
        executor=executor,
        recovery_orchestrator=recovery,
        instrumentation=instrumentation,
        output_verifier=output_verifier,
        output_schemas=TOOL_OUTPUT_SCHEMAS,
    )


def inject_degradation(registry: ToolRegistry) -> None:
    """Inject a degraded version of get_weather that returns wrong output."""
    def degraded_get_weather(city: str) -> str:
        """Returns wrong city temperature to trigger regression."""
        temperatures = {"london": 5, "paris": 8, "tokyo": 12}
        temp = temperatures.get(city.lower(), 0)
        return f"Weather in {city}: {temp}°C, heavy rain"

    registry.register(
        "get_weather",
        degraded_get_weather,
        input_schema=TOOL_INPUT_SCHEMAS["get_weather"],
        output_schema=TOOL_OUTPUT_SCHEMAS["get_weather"],
        description="Get weather for a city (degraded version).",
    )


async def run_eval(
    registry: ToolRegistry,
    dataset: InMemoryDataset,
    label: str,
) -> Any:
    """Run a single evaluation pass and return the report."""
    print(f"\n{'='*60}")
    print(f"  RUN: {label}")
    print(f"{'='*60}")

    # Create agent factory that returns a fresh agent per case
    def agent_factory():
        return create_agent(registry)

    # Build per-case custom agent factory that uses correct FixedPlanner
    async def run_case(case: EvaluationCase) -> Any:
        plan = build_plan_for_case(case)
        agent = create_agent(registry)
        agent._planner = FixedPlanner(plan)
        return await agent.run(
            goal=case.goal,
            tool_descriptions=registry.get_descriptions(),
        )

    # Create a custom runner that uses the agent factory
    # We need to override the default runner to use per-case planners
    # Using the EvaluationRunner with a lambda-based approach

    metrics = [
        ExactMatchMetric(),
        SuccessRateMetric(),
        LatencyMetric(),
        RecoveryCountMetric(),
    ]

    # Load dataset
    _reset_state()

    # We'll manually orchestrate since each case needs a different planner
    from neo_mcp.evaluation.runner import EvaluationReport

    report = EvaluationReport(
        config={"metrics": [m.name for m in metrics], "label": label},
        dataset_version=dataset.version(),
    )

    from neo_mcp.evaluation.scoring import MetricResult

    import time
    start = time.monotonic()

    for case in dataset.all_cases():
        _reset_state()
        try:
            agent_result = await run_case(case)
            case_success = True
            case_error = None
        except Exception as e:
            from neo_mcp.agent.orchestrator import AgentResult
            agent_result = AgentResult(
                goal=case.goal,
                step_results=[],
                incidents=[],
                plan=None,
                success=False,
                summary=f"Error: {type(e).__name__}: {e}",
            )
            case_success = False
            case_error = str(e)

        # Score
        case_metrics = []
        for metric in metrics:
            try:
                mr = metric.score(case, agent_result)
                case_metrics.append(mr)
            except Exception as e:
                case_metrics.append(MetricResult(
                    metric_name=metric.name, score=0.0,
                    details={"error": str(e)}, success=False,
                ))

        report.per_case_results.append({
            "case_id": case.case_id,
            "goal": case.goal,
            "expected_output": case.expected_output,
            "success": case_success,
            "error": case_error,
            "metrics": [
                {"metric_name": m.metric_name, "score": m.score,
                 "details": m.details, "success": m.success}
                for m in case_metrics
            ],
            "agent_success": agent_result.success,
            "num_incidents": len(agent_result.incidents),
            "num_steps": len(agent_result.step_results),
        })

    report.total_duration_seconds = round(time.monotonic() - start, 3)
    report.num_cases = len(report.per_case_results)
    report.num_successful = sum(1 for cr in report.per_case_results if cr["success"])

    # Aggregate scores
    aggregator = ScoreAggregator()
    all_results = {}
    for case_result in report.per_case_results:
        cid = case_result["case_id"]
        all_results[cid] = [
            MetricResult(m["metric_name"], m["score"], m["details"], m["success"])
            for m in case_result["metrics"]
        ]
    report.aggregated_summary = aggregator.aggregate(all_results)

    # Print results
    print(f"\nResults for {label}:")
    for cr in report.per_case_results:
        print(f"  [{cr['case_id']}] success={cr['success']} "
              f"agent_success={cr['agent_success']} "
              f"incidents={cr['num_incidents']}")
        for m in cr["metrics"]:
            print(f"    {m['metric_name']}: {m['score']:.4f} (pass={m['success']})")

    print(f"\nAggregated Summary:")
    for metric_name, stats in report.aggregated_summary.items():
        print(f"  {metric_name}: mean={stats['mean']:.4f} "
              f"min={stats['min']:.4f} max={stats['max']:.4f} "
              f"success_rate={stats['success_rate']:.4f}")

    print(f"  Duration: {report.total_duration_seconds:.2f}s")
    print(f"  Cases: {report.num_cases} total, {report.num_successful} successful")

    return report


async def main() -> None:
    """Run the full E2E evaluation demo."""
    print("=" * 60)
    print("  NEO-MCP EVALUATION LAYER — E2E DEMO")
    print("=" * 60)

    # Create temp file for baseline storage
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        baseline_path = f.name
        f.write("[]")

    try:
        # Setup
        registry = setup_tools()
        dataset = create_dataset()
        baseline_store = JsonBaselineStore(filepath=baseline_path)
        detector = RegressionDetector(baseline_store=baseline_store, default_threshold=0.1)
        review_queue = InMemoryReviewQueue()

        # Run 1: Establish baseline
        report1 = await run_eval(registry, dataset, "BASELINE")

        # Save baseline
        await detector.save_baseline(
            report1.aggregated_summary,
            run_id="baseline_run",
        )
        print(f"\n✓ Baseline saved ({len(dataset.all_cases())} cases)")

        # Run 2: Inject degradation
        print(f"\n{'='*60}")
        print("  INJECTING DEGRADATION: get_weather returning wrong temperatures")
        print(f"{'='*60}")
        inject_degradation(registry)
        dataset._version = "1.0.1"  # Bump version

        report2 = await run_eval(registry, dataset, "DEGRADED RUN")

        # Detect regressions
        verdicts = await detector.compare(report2.aggregated_summary)
        print(f"\n{'='*60}")
        print("  REGRESSION DETECTION")
        print(f"{'='*60}")
        if verdicts:
            for v in verdicts:
                status = "❌ REGRESSION" if not v.passed else "✓ OK"
                icon = "⬆" if v.regression_type == "score_increased" else "➖"
                print(f"  [{status}] {v.metric_name}: "
                      f"current={v.current_score:.4f} baseline={v.baseline_score:.4f} "
                      f"delta={v.delta:.4f} threshold={v.threshold} {icon}")
                print(f"    {v.details}")

                # Enqueue failures for review
                if not v.passed:
                    review_queue.enqueue(ReviewEntry(
                        case_id="all_cases",
                        metric_name=v.metric_name,
                        score=v.current_score,
                        details={
                            "baseline": v.baseline_score,
                            "delta": v.delta,
                            "threshold": v.threshold,
                            "regression_type": v.regression_type,
                        },
                    ))

        # Show review queue
        pending = review_queue.pending()
        print(f"\n{'='*60}")
        print("  REVIEW QUEUE")
        print(f"{'='*60}")
        if pending:
            for entry in pending:
                print(f"\n  📋 Review #{entry.entry_id}")
                print(f"     Metric: {entry.metric_name}")
                print(f"     Score: {entry.score}")
                print(f"     Created: {entry.created_at}")
                print(f"     Status: {entry.status.name}")

            # Resolve one as an example
            resolved = review_queue.resolve(
                pending[0].entry_id,
                ReviewStatus.APPROVED,
                "Reviewed — degradation confirmed, investigation needed",
            )
            if resolved:
                entry = review_queue.get_entry(pending[0].entry_id)
                print(f"\n  ✓ Resolved #{entry.entry_id}: {entry.status.name}")
                print(f"    Notes: {entry.reviewer_notes}")
        else:
            print("  No regressions requiring review.")

        # Print overall results
        print(f"\n{'='*60}")
        print("  FINAL VERDICT")
        print(f"{'='*60}")
        has_regression = any(not v.passed for v in verdicts)
        if has_regression:
            print("  ❌ REGRESSIONS DETECTED — Review queue populated")
        else:
            print("  ✓ ALL CHECKS PASSED — No regressions found")

        print(f"\n{'='*60}")
        print("  DEMO COMPLETE")
        print(f"{'='*60}")

    finally:
        import os
        if os.path.exists(baseline_path):
            os.unlink(baseline_path)


if __name__ == "__main__":
    asyncio.run(main())