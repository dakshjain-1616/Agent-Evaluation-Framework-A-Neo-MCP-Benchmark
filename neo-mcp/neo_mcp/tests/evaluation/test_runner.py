"""Unit tests for evaluation runner module."""

import pytest

from neo_mcp.agent.orchestrator import AgentResult, SelfHealingAgent
from neo_mcp.core.models import Plan, Step, StepResult, Verdict
from neo_mcp.evaluation.datasets import EvaluationCase, InMemoryDataset
from neo_mcp.evaluation.runner import EvaluationRunner, EvaluationReport
from neo_mcp.evaluation.scoring import EvaluationMetric, MetricResult


class FakeMetric(EvaluationMetric):
    """Simple metric that returns a fixed score."""

    def __init__(self, name: str = "fake", score: float = 1.0):
        self._name = name
        self._score = score

    @property
    def name(self) -> str:
        return self._name

    def score(self, case, agent_result) -> MetricResult:
        return MetricResult(
            metric_name=self._name,
            score=self._score,
            success=self._score > 0,
        )


class BrokenMetric(EvaluationMetric):
    """Metric that always raises an exception during scoring."""

    @property
    def name(self) -> str:
        return "broken"

    def score(self, case, agent_result) -> MetricResult:
        raise ValueError("Metric failed")


class FakeAgent:
    """A minimal fake agent for testing."""

    def __init__(self, success: bool = True, summary: str = "ok"):
        self._success = success
        self._summary = summary

    async def run(self, goal: str, tool_descriptions=None) -> AgentResult:
        return AgentResult(
            goal=goal,
            step_results=[],
            incidents=[],
            plan=None,
            success=self._success,
            summary=self._summary,
        )


class TestEvaluationRunner:
    """Test EvaluationRunner basic functionality."""

    def setup_method(self):
        self.cases = [
            EvaluationCase(case_id="c1", goal="Goal 1", expected_output="out1"),
            EvaluationCase(case_id="c2", goal="Goal 2", expected_output="out2"),
        ]
        self.dataset = InMemoryDataset(cases=self.cases, version="1.0.0")

    @pytest.mark.asyncio
    async def test_run_all_cases(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
        )
        report = await runner.run()
        assert isinstance(report, EvaluationReport)
        assert report.num_cases == 2
        assert report.num_successful == 2
        assert len(report.per_case_results) == 2
        assert report.dataset_version == "1.0.0"

    @pytest.mark.asyncio
    async def test_run_with_case_filter(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
        )
        report = await runner.run(case_filter=["c1"])
        assert report.num_cases == 1
        assert report.per_case_results[0]["case_id"] == "c1"

    @pytest.mark.asyncio
    async def test_run_with_empty_filter(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
        )
        report = await runner.run(case_filter=[])
        assert report.num_cases == 0

    @pytest.mark.asyncio
    async def test_aggregated_summary_present(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
        )
        report = await runner.run()
        assert "fake1" in report.aggregated_summary
        assert report.aggregated_summary["fake1"]["mean"] == 1.0
        assert report.aggregated_summary["fake1"]["count"] == 2

    @pytest.mark.asyncio
    async def test_broken_agent_does_not_crash_runner(self):
        """If an agent raises, runner should handle gracefully."""
        agent_call_count = [0]

        class CrashInThirdCall:
            async def run(self, goal, tool_descriptions=None):
                agent_call_count[0] += 1
                raise RuntimeError("Simulated agent crash")

        runner = EvaluationRunner(
            agent_factory=lambda: CrashInThirdCall(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
        )
        report = await runner.run()
        assert report.num_cases == 2
        assert report.num_successful == 0  # Both crashed
        # Both should have an error field
        for cr in report.per_case_results:
            assert cr["error"] is not None

    @pytest.mark.asyncio
    async def test_broken_metric_does_not_crash_runner(self):
        """If a metric raises, runner should handle gracefully."""
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[BrokenMetric()],
        )
        report = await runner.run()
        assert report.num_cases == 2
        for cr in report.per_case_results:
            metrics = cr["metrics"]
            assert len(metrics) == 1
            assert metrics[0]["metric_name"] == "broken"
            assert metrics[0]["score"] == 0.0  # Default on error
            assert "error" in metrics[0]["details"]

    @pytest.mark.asyncio
    async def test_seed_set_in_config(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
            seed=42,
        )
        report = await runner.run()
        assert report.config["seed"] == 42

    @pytest.mark.asyncio
    async def test_max_concurrency_set_in_config(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="fake1", score=1.0)],
            max_concurrency=5,
        )
        report = await runner.run()
        assert report.config["max_concurrency"] == 5

    @pytest.mark.asyncio
    async def test_metrics_listed_in_config(self):
        runner = EvaluationRunner(
            agent_factory=lambda: FakeAgent(),  # type: ignore
            dataset=self.dataset,
            metrics=[FakeMetric(name="m1"), FakeMetric(name="m2")],
        )
        report = await runner.run()
        assert "m1" in report.config["metrics"]
        assert "m2" in report.config["metrics"]


class TestEvaluationReport:
    """Test EvaluationReport dataclass."""

    def test_default_values(self):
        report = EvaluationReport()
        assert report.per_case_results == []
        assert report.aggregated_summary == {}
        assert report.num_cases == 0
        assert report.num_successful == 0
        assert report.total_duration_seconds == 0.0