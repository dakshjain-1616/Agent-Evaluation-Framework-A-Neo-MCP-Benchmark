"""Evaluation runner — orchestrates running SelfHealingAgent over a dataset.

The EvaluationRunner takes an agent factory, dataset, and list of metrics,
runs each case with bounded asyncio concurrency, and produces an EvaluationReport.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neo_mcp.agent.orchestrator import AgentResult, SelfHealingAgent
from neo_mcp.evaluation.datasets import EvaluationCase, EvaluationDataset
from neo_mcp.evaluation.scoring import EvaluationMetric, MetricResult, ScoreAggregator


@dataclass
class EvaluationReport:
    """Complete report from running an evaluation.

    Attributes:
        per_case_results: List of dicts, one per case, with case_id, goal, success,
            metrics, incidents, error, and duration.
        aggregated_summary: Dict mapping metric_name to {mean, min, max, std, count, success_rate}.
        config: Dict of evaluation configuration (max_concurrency, seed, metrics used, etc.).
        dataset_version: Version string from the dataset.
        total_duration_seconds: Total wall-clock time for the evaluation run.
        num_cases: Total number of cases evaluated.
        num_successful: Number of cases that succeeded (no errors during run).
    """

    per_case_results: List[Dict[str, Any]] = field(default_factory=list)
    aggregated_summary: Dict[str, Dict[str, float]] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    dataset_version: str = ""
    total_duration_seconds: float = 0.0
    num_cases: int = 0
    num_successful: int = 0


class EvaluationRunner:
    """Runs SelfHealingAgent evaluations over a dataset with bounded concurrency.

    Usage:
        runner = EvaluationRunner(
            agent_factory=lambda: my_agent,
            dataset=my_dataset,
            metrics=[ExactMatchMetric(), SuccessRateMetric()],
        )
        report = await runner.run()
    """

    def __init__(
        self,
        agent_factory: Callable[[], SelfHealingAgent],
        dataset: EvaluationDataset,
        metrics: List[EvaluationMetric],
        max_concurrency: int = 3,
        seed: Optional[int] = None,
        tool_descriptions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._dataset = dataset
        self._metrics = metrics
        self._max_concurrency = max_concurrency
        self._seed = seed
        self._tool_descriptions = tool_descriptions

    async def run(
        self,
        case_filter: Optional[List[str]] = None,
    ) -> EvaluationReport:
        """Run the full evaluation.

        Args:
            case_filter: Optional list of case_ids to run. If None, runs all cases.

        Returns:
            EvaluationReport with per-case and aggregated results.
        """
        # Set seed for reproducibility
        if self._seed is not None:
            random.seed(self._seed)

        # Ensure dataset is loaded
        self._dataset.load()
        all_cases = self._dataset.all_cases()

        if case_filter is not None:
            if len(case_filter) == 0:
                cases = []
            else:
                cases = [c for c in all_cases if c.case_id in case_filter]
        else:
            cases = list(all_cases)

        if not cases:
            return EvaluationReport(
                config=self._build_config(),
                dataset_version=self._dataset.version(),
            )

        start_time = time.monotonic()

        # Run cases with bounded concurrency
        semaphore = asyncio.Semaphore(self._max_concurrency)
        aggregator = ScoreAggregator()
        all_metric_results: Dict[str, List[MetricResult]] = {}
        per_case_results: List[Dict[str, Any]] = []
        num_successful = 0

        async def run_single_case(case: EvaluationCase) -> Dict[str, Any]:
            """Run a single case with graceful error handling."""
            async with semaphore:
                case_start = time.monotonic()
                case_error: Optional[str] = None
                agent_result: Optional[AgentResult] = None
                metric_results: List[MetricResult] = []

                try:
                    agent = self._agent_factory()
                    agent_result = await agent.run(
                        goal=case.goal,
                        tool_descriptions=self._tool_descriptions,
                    )
                except Exception as e:
                    case_error = f"{type(e).__name__}: {e}"
                    # Create a minimal agent result for scoring
                    agent_result = AgentResult(
                        goal=case.goal,
                        step_results=[],
                        incidents=[],
                        plan=None,
                        success=False,
                        summary=f"Error: {case_error}",
                    )

                # Score the result
                for metric in self._metrics:
                    try:
                        mr = metric.score(case, agent_result)
                        metric_results.append(mr)
                    except Exception as e:
                        metric_results.append(
                            MetricResult(
                                metric_name=metric.name,
                                score=0.0,
                                details={"error": str(e)},
                                success=False,
                            )
                        )

                case_duration = time.monotonic() - case_start
                is_success = case_error is None

                return {
                    "case_id": case.case_id,
                    "goal": case.goal,
                    "expected_output": case.expected_output,
                    "success": is_success,
                    "error": case_error,
                    "duration_seconds": round(case_duration, 3),
                    "metrics": [
                        {
                            "metric_name": mr.metric_name,
                            "score": mr.score,
                            "details": mr.details,
                            "success": mr.success,
                        }
                        for mr in metric_results
                    ],
                    "agent_success": agent_result.success if agent_result else False,
                    "num_incidents": len(agent_result.incidents) if agent_result else 0,
                    "num_steps": len(agent_result.step_results) if agent_result else 0,
                }

        # Create tasks for all cases
        tasks = [run_single_case(case) for case in cases]
        results = await asyncio.gather(*tasks)

        # Collect results
        for idx, case_result in enumerate(results):
            per_case_results.append(case_result)
            if case_result["success"]:
                num_successful += 1

            # Collect metric results for aggregation
            case_id = case_result["case_id"]
            case_metric_results = []
            for m in case_result["metrics"]:
                case_metric_results.append(
                    MetricResult(
                        metric_name=m["metric_name"],
                        score=m["score"],
                        details=m["details"],
                        success=m["success"],
                    )
                )
            all_metric_results[case_id] = case_metric_results

        total_duration = time.monotonic() - start_time

        # Aggregate scores across all cases
        aggregated = aggregator.aggregate(all_metric_results)

        return EvaluationReport(
            per_case_results=per_case_results,
            aggregated_summary=aggregated,
            config=self._build_config(),
            dataset_version=self._dataset.version(),
            total_duration_seconds=round(total_duration, 3),
            num_cases=len(cases),
            num_successful=num_successful,
        )

    def _build_config(self) -> Dict[str, Any]:
        """Build configuration dict for the report."""
        return {
            "max_concurrency": self._max_concurrency,
            "seed": self._seed,
            "metrics": [m.name for m in self._metrics],
            "dataset_version": self._dataset.version(),
            "num_cases": len(self._dataset.all_cases()) if self._dataset else 0,
        }