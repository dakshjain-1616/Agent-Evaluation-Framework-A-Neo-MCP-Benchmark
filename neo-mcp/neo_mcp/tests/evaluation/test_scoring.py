"""Unit tests for scoring module: metrics and aggregator."""

import pytest

from neo_mcp.agent.orchestrator import AgentResult
from neo_mcp.core.models import Plan, Step, StepResult, Verdict
from neo_mcp.evaluation.datasets import EvaluationCase
from neo_mcp.evaluation.scoring import (
    ExactMatchMetric,
    LatencyMetric,
    MetricResult,
    RecoveryCountMetric,
    ScoreAggregator,
    SuccessRateMetric,
)


class TestExactMatchMetric:
    """Test ExactMatchMetric scoring."""

    def setup_method(self):
        self.metric = ExactMatchMetric()

    def test_name(self):
        assert self.metric.name == "exact_match"

    def test_exact_match(self):
        case = EvaluationCase(case_id="t1", goal="X", expected_output="Hello World")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], summary="Hello World"
        )
        mr = self.metric.score(case, result)
        assert mr.score == 1.0
        assert mr.success is True

    def test_mismatch(self):
        case = EvaluationCase(case_id="t2", goal="X", expected_output="Hello World")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], summary="Goodbye World"
        )
        mr = self.metric.score(case, result)
        assert mr.score == 0.0
        assert mr.success is False

    def test_empty_expected_vs_actual(self):
        case = EvaluationCase(case_id="t3", goal="X", expected_output="")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], summary=None
        )
        mr = self.metric.score(case, result)
        assert mr.score == 1.0  # Both empty
        assert mr.success is True

    def test_case_sensitive(self):
        case = EvaluationCase(case_id="t4", goal="X", expected_output="Hello")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], summary="hello"
        )
        mr = self.metric.score(case, result)
        assert mr.score == 0.0  # Case-sensitive: mismatch


class TestSuccessRateMetric:
    """Test SuccessRateMetric scoring."""

    def setup_method(self):
        self.metric = SuccessRateMetric()

    def test_name(self):
        assert self.metric.name == "success_rate"

    def test_successful_agent(self):
        case = EvaluationCase(case_id="t1", goal="X", expected_output="ok")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], success=True
        )
        mr = self.metric.score(case, result)
        assert mr.score == 1.0
        assert mr.success is True

    def test_failed_agent(self):
        case = EvaluationCase(case_id="t2", goal="X", expected_output="ok")
        result = AgentResult(
            goal="X", step_results=[], incidents=[], success=False
        )
        mr = self.metric.score(case, result)
        assert mr.score == 0.0
        assert mr.success is False

    def test_incidents_count_in_details(self):
        case = EvaluationCase(case_id="t3", goal="X", expected_output="ok")
        result = AgentResult(
            goal="X", step_results=[], incidents=[{"step_id": "s1"}],
            success=False,
        )
        mr = self.metric.score(case, result)
        assert mr.details["num_incidents"] == 1


class TestLatencyMetric:
    """Test LatencyMetric scoring."""

    def setup_method(self):
        self.metric = LatencyMetric()

    def test_name(self):
        assert self.metric.name == "latency"

    def test_no_steps(self):
        case = EvaluationCase(case_id="t1", goal="X", expected_output="")
        result = AgentResult(goal="X", step_results=[], incidents=[])
        mr = self.metric.score(case, result)
        assert mr.score == 0.0  # No steps = 0 latency
        assert mr.success is True

    def test_with_step_durations(self):
        case = EvaluationCase(case_id="t2", goal="X", expected_output="")
        step = Step(step_id="s1", tool_name="t1", arguments={})
        results = [
            StepResult(step=step, success=True, duration_ms=100.0, verdict=Verdict.SUCCESS),
            StepResult(step=step, success=True, duration_ms=200.0, verdict=Verdict.SUCCESS),
        ]
        result = AgentResult(goal="X", step_results=results, incidents=[])
        mr = self.metric.score(case, result)
        assert mr.score == 0.3  # 300ms = 0.3 seconds
        assert mr.details["avg_duration_ms"] == 150.0


class TestRecoveryCountMetric:
    """Test RecoveryCountMetric scoring."""

    def setup_method(self):
        self.metric = RecoveryCountMetric()

    def test_name(self):
        assert self.metric.name == "recovery_count"

    def test_no_incidents(self):
        case = EvaluationCase(case_id="t1", goal="X", expected_output="")
        result = AgentResult(goal="X", step_results=[], incidents=[])
        mr = self.metric.score(case, result)
        assert mr.score == 0.0
        assert mr.success is True

    def test_with_incidents(self):
        case = EvaluationCase(case_id="t2", goal="X", expected_output="")
        incidents = [
            {"step_id": "s1", "final_verdict": "RECOVERED"},
            {"step_id": "s2", "final_verdict": "FAILURE"},
        ]
        result = AgentResult(goal="X", step_results=[], incidents=incidents)
        mr = self.metric.score(case, result)
        assert mr.score == 2.0
        assert mr.success is False  # Incidents present


class TestScoreAggregator:
    """Test ScoreAggregator aggregation logic."""

    def setup_method(self):
        self.aggregator = ScoreAggregator()

    def test_empty_results(self):
        summary = self.aggregator.aggregate({})
        assert summary == {}

    def test_single_metric_single_case(self):
        results = {
            "case_1": [
                MetricResult(metric_name="exact_match", score=1.0, success=True),
            ],
        }
        summary = self.aggregator.aggregate(results)
        assert "exact_match" in summary
        assert summary["exact_match"]["mean"] == 1.0
        assert summary["exact_match"]["min"] == 1.0
        assert summary["exact_match"]["max"] == 1.0
        assert summary["exact_match"]["count"] == 1
        assert summary["exact_match"]["success_rate"] == 1.0

    def test_multiple_metrics_multiple_cases(self):
        results = {
            "case_1": [
                MetricResult(metric_name="exact_match", score=1.0, success=True),
                MetricResult(metric_name="success_rate", score=1.0, success=True),
            ],
            "case_2": [
                MetricResult(metric_name="exact_match", score=0.0, success=False),
                MetricResult(metric_name="success_rate", score=1.0, success=True),
            ],
        }
        summary = self.aggregator.aggregate(results)
        # exact_match: scores = [1.0, 0.0]
        assert summary["exact_match"]["mean"] == 0.5
        assert summary["exact_match"]["min"] == 0.0
        assert summary["exact_match"]["max"] == 1.0
        assert summary["exact_match"]["count"] == 2
        assert summary["exact_match"]["success_rate"] == 0.5
        # success_rate: scores = [1.0, 1.0]
        assert summary["success_rate"]["mean"] == 1.0
        assert summary["success_rate"]["success_rate"] == 1.0

    def test_single_case_std_is_zero(self):
        results = {
            "case_1": [
                MetricResult(metric_name="latency", score=5.0, success=True),
            ],
        }
        summary = self.aggregator.aggregate(results)
        assert summary["latency"]["std"] == 0.0


class TestMetricResult:
    """Test MetricResult dataclass."""

    def test_default_values(self):
        mr = MetricResult(metric_name="test", score=0.5)
        assert mr.metric_name == "test"
        assert mr.score == 0.5
        assert mr.details == {}
        assert mr.success is False