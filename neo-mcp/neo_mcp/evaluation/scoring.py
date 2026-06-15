"""Scoring and metrics for evaluation results.

Provides EvaluationMetric ABC with concrete implementations for exact match,
success rate, latency, and recovery counting. ScoreAggregator rolls per-case
results into run-level summary statistics.
"""

from __future__ import annotations

import abc
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neo_mcp.agent.orchestrator import AgentResult
from neo_mcp.evaluation.datasets import EvaluationCase


@dataclass
class MetricResult:
    """The result of scoring a single case with a single metric.

    Attributes:
        metric_name: Name of the metric that produced this result.
        score: The numeric score (metric-specific scale).
        details: Additional details or breakdown for this score.
        success: Whether this score indicates success (threshold varies by metric).
    """

    metric_name: str
    score: float
    details: Dict[str, Any] = field(default_factory=dict)
    success: bool = False


class EvaluationMetric(abc.ABC):
    """Abstract base class for evaluation metrics.

    A metric takes an EvaluationCase and an AgentResult and produces a MetricResult.
    """

    @abc.abstractmethod
    def score(
        self,
        case: EvaluationCase,
        agent_result: AgentResult,
    ) -> MetricResult:
        """Score a single evaluation case against an agent result.

        Args:
            case: The evaluation case (contains expected output).
            agent_result: The result from SelfHealingAgent.run().

        Returns:
            MetricResult with score, details, and success flag.
        """
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Return the name of this metric."""
        ...


class ExactMatchMetric(EvaluationMetric):
    """Compares agent_result.summary or step_result output to case.expected_output.

    Returns 1.0 if the strings match exactly (case-sensitive), 0.0 otherwise.
    """

    @property
    def name(self) -> str:
        return "exact_match"

    def score(
        self,
        case: EvaluationCase,
        agent_result: AgentResult,
    ) -> MetricResult:
        """Score based on exact string match of summary vs expected_output."""
        actual = agent_result.summary if agent_result.summary else ""
        expected = case.expected_output if case.expected_output else ""
        is_match = actual == expected
        return MetricResult(
            metric_name=self.name,
            score=1.0 if is_match else 0.0,
            details={
                "expected": expected,
                "actual": actual,
                "truncated_expected": len(expected) > 200,
                "truncated_actual": len(actual) > 200,
            },
            success=is_match,
        )


class SuccessRateMetric(EvaluationMetric):
    """Returns 1.0 if the agent result indicates success, 0.0 otherwise.

    Uses agent_result.success to determine success.
    """

    @property
    def name(self) -> str:
        return "success_rate"

    def score(
        self,
        case: EvaluationCase,
        agent_result: AgentResult,
    ) -> MetricResult:
        """Score based on agent_result.success."""
        is_success = agent_result.success
        return MetricResult(
            metric_name=self.name,
            score=1.0 if is_success else 0.0,
            details={
                "success": is_success,
                "num_steps": len(agent_result.step_results),
                "num_incidents": len(agent_result.incidents),
            },
            success=is_success,
        )


class LatencyMetric(EvaluationMetric):
    """Measures execution latency from agent results.

    Extracts duration from step_results if available, or uses total duration
    derived from the difference between first and last step timestamps.
    Returns total wall-clock time in seconds if available, else -1.0.
    """

    @property
    def name(self) -> str:
        return "latency"

    def score(
        self,
        case: EvaluationCase,
        agent_result: AgentResult,
    ) -> MetricResult:
        """Score based on execution latency.

        Returns total step duration sum in seconds.
        A lower score is better (faster execution).
        """
        total_duration_ms = sum(
            r.duration_ms for r in agent_result.step_results
        )
        total_duration_seconds = total_duration_ms / 1000.0

        step_count = len(agent_result.step_results)
        avg_duration_ms = (
            total_duration_ms / step_count if step_count > 0 else 0.0
        )

        return MetricResult(
            metric_name=self.name,
            score=total_duration_seconds,
            details={
                "total_duration_ms": total_duration_ms,
                "avg_duration_ms": round(avg_duration_ms, 2),
                "step_count": step_count,
            },
            success=True,  # Latency is informational, not pass/fail
        )


class RecoveryCountMetric(EvaluationMetric):
    """Counts recovery incidents in the agent result.

    Returns the number of incidents (recovery events). Lower is better.
    A score of 0 means no recovery was needed.
    """

    @property
    def name(self) -> str:
        return "recovery_count"

    def score(
        self,
        case: EvaluationCase,
        agent_result: AgentResult,
    ) -> MetricResult:
        """Score based on number of recovery incidents."""
        incident_count = len(agent_result.incidents)
        return MetricResult(
            metric_name=self.name,
            score=float(incident_count),
            details={
                "incident_count": incident_count,
                "verdicts": [
                    inc.get("final_verdict", "unknown")
                    for inc in agent_result.incidents
                ],
            },
            success=incident_count == 0,
        )


class ScoreAggregator:
    """Aggregates per-case metric results into run-level summary statistics.

    Produces mean, min, max, and standard deviation for each metric across cases.
    """

    def aggregate(
        self,
        results: Dict[str, List[MetricResult]],
    ) -> Dict[str, Dict[str, float]]:
        """Aggregate metric results across all cases.

        Args:
            results: Mapping of case_id -> list of MetricResult objects.

        Returns:
            Dict mapping metric_name -> {mean, min, max, std, count}.
        """
        if not results:
            return {}

        # Collect scores per metric
        metric_scores: Dict[str, List[float]] = {}
        metric_successes: Dict[str, List[bool]] = {}

        for case_id, metric_results in results.items():
            for mr in metric_results:
                if mr.metric_name not in metric_scores:
                    metric_scores[mr.metric_name] = []
                    metric_successes[mr.metric_name] = []
                metric_scores[mr.metric_name].append(mr.score)
                metric_successes[mr.metric_name].append(mr.success)

        summary: Dict[str, Dict[str, float]] = {}
        for metric_name, scores in metric_scores.items():
            n = len(scores)
            if n == 0:
                continue
            mean_val = sum(scores) / n
            min_val = min(scores)
            max_val = max(scores)

            # Standard deviation
            if n > 1:
                variance = sum((s - mean_val) ** 2 for s in scores) / n
                std_val = math.sqrt(variance)
            else:
                std_val = 0.0

            successes = metric_successes.get(metric_name, [])
            success_rate = sum(successes) / n if n > 0 else 0.0

            summary[metric_name] = {
                "mean": round(mean_val, 4),
                "min": round(min_val, 4),
                "max": round(max_val, 4),
                "std": round(std_val, 4),
                "count": n,
                "success_rate": round(success_rate, 4),
            }

        return summary