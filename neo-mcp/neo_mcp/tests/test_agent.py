"""Unit tests for SelfHealingAgent — all components mocked, no real API calls."""

import pytest

from neo_mcp.core.models import (
    FailureCategory,
    FailureClassification,
    Plan,
    RecoveryAction,
    Step,
    StepResult,
    Verdict,
)
from neo_mcp.agent.orchestrator import SelfHealingAgent


class FakePlanner:
    """Returns a predefined plan."""

    def __init__(self, steps):
        self._steps = steps

    async def plan(self, goal, tool_descriptions):
        return Plan(goal=goal, steps=self._steps)


class FakeExecutor:
    """Returns results based on step tool_name."""

    def __init__(self, results_map=None):
        self._results_map = results_map or {}

    async def execute_step(self, step):
        if step.tool_name in self._results_map:
            return self._results_map[step.tool_name]
        return StepResult(
            step=step, success=True, output="ok", verdict=Verdict.SUCCESS,
        )


class FakeRecoveryOrchestrator:
    """Simulates recovery outcome."""

    def __init__(self, verdict=Verdict.RECOVERED, resolved=True):
        self._verdict = verdict
        self._resolved = resolved

    async def recover(self, step, initial_error, exception_type, **kwargs):
        from neo_mcp.core.models import IncidentRecord
        return IncidentRecord(
            step=step,
            original_error=initial_error,
            classification=None,
            attempts=[],
            final_verdict=self._verdict,
            resolved=self._resolved,
        )


class FakeInstrumentation:
    def __init__(self):
        self.logs = []
        self.metrics = {}
        self.traces = []

    def log(self, level, message, **context):
        self.logs.append((level, message, context))

    def increment(self, metric_name, **tags):
        self.metrics[metric_name] = self.metrics.get(metric_name, 0) + 1

    def record_trace(self, step_id, event, duration_ms, **attributes):
        self.traces.append((step_id, event, duration_ms, attributes))

    def get_logs(self):
        return self.logs

    def get_metrics_snapshot(self):
        return self.metrics

    def get_traces(self):
        return self.traces

    def clear(self):
        self.logs.clear()
        self.metrics.clear()
        self.traces.clear()


class TestSelfHealingAgent:
    """Test the full agent orchestration loop."""

    @pytest.mark.asyncio
    async def test_run_all_successful_steps(self):
        """All steps succeed, no recovery needed."""
        steps = [
            Step(step_id="1", tool_name="ping", arguments={}, description="Ping"),
            Step(step_id="2", tool_name="echo", arguments={"msg": "hi"}, description="Echo"),
        ]
        planner = FakePlanner(steps)
        executor = FakeExecutor({
            "ping": StepResult(step=steps[0], success=True, output="pong", verdict=Verdict.SUCCESS),
            "echo": StepResult(step=steps[1], success=True, output="hi", verdict=Verdict.SUCCESS),
        })
        orchestrator = FakeRecoveryOrchestrator()
        instrumentation = FakeInstrumentation()

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
        )

        result = await agent.run("Test goal")

        assert len(result.step_results) == 2
        assert all(r.success for r in result.step_results)
        assert result.goal == "Test goal"
        assert len(result.incidents) == 0  # No failures → no incidents

    @pytest.mark.asyncio
    async def test_run_with_recovery_on_failure(self):
        """Failed step triggers recovery orchestrator."""
        steps = [
            Step(step_id="1", tool_name="failing_tool", arguments={}, description="Fail step"),
        ]
        planner = FakePlanner(steps)

        # Executor returns failure for the first step
        results_map = {
            "failing_tool": StepResult(
                step=steps[0], success=False, output=None,
                error="rate limit", exception_type="RuntimeError",
                verdict=Verdict.FAILURE,
            ),
        }

        class RecordingExecutor:
            def __init__(self, results_map):
                self._results_map = results_map
                self.executed_steps = []

            async def execute_step(self, step):
                self.executed_steps.append(step)
                return self._results_map.get(step.tool_name, StepResult(
                    step=step, success=True, output="ok", verdict=Verdict.SUCCESS))

        executor = RecordingExecutor(results_map)
        orchestrator = FakeRecoveryOrchestrator(verdict=Verdict.RECOVERED, resolved=True)
        instrumentation = FakeInstrumentation()

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
        )

        result = await agent.run("Test goal")

        assert len(result.incidents) == 1
        assert result.incidents[0]["final_verdict"] == "RECOVERED"
        assert result.step_results[0].verdict == Verdict.RECOVERED

    @pytest.mark.asyncio
    async def test_run_with_unrecoverable_failure(self):
        """Failed step that cannot be recovered → FAILURE verdict on step."""
        steps = [
            Step(step_id="1", tool_name="bad", arguments={}, description="Bad step"),
        ]
        planner = FakePlanner(steps)

        results_map = {
            "bad": StepResult(
                step=steps[0], success=False, output=None,
                error="401 Unauthorized", exception_type="RuntimeError",
                verdict=Verdict.FAILURE,
            ),
        }

        executor = FakeExecutor(results_map)
        orchestrator = FakeRecoveryOrchestrator(verdict=Verdict.FAILURE, resolved=True)
        instrumentation = FakeInstrumentation()

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
        )

        result = await agent.run("Test goal")

        assert len(result.incidents) == 1
        assert result.incidents[0]["final_verdict"] == "FAILURE"
        assert result.step_results[0].verdict == Verdict.FAILURE

    @pytest.mark.asyncio
    async def test_run_output_verification_failure(self):
        """Successful step with bad output gets verified and triggers recovery."""
        steps = [
            Step(step_id="1", tool_name="validate_report", arguments={"data": "test"}, description="Validate"),
        ]
        planner = FakePlanner(steps)

        executor = FakeExecutor({
            "validate_report": StepResult(
                step=steps[0], success=True, output={"result": "incomplete"},
                verdict=Verdict.SUCCESS,
            ),
        })

        orchestrator = FakeRecoveryOrchestrator(verdict=Verdict.RECOVERED, resolved=True)
        instrumentation = FakeInstrumentation()

        # Schema that requires 'status' field
        output_schemas = {
            "validate_report": {
                "type": "object",
                "properties": {"status": {"type": "string"}, "result": {"type": "string"}},
                "required": ["status", "result"],
            }
        }

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
            output_verifier=None,  # Will be set after __init__
            output_schemas=output_schemas,
        )

        # Set a verifier that fails
        class StrictVerifier:
            def verify(self, output, step, output_schema=None):
                return False  # All outputs fail verification

        agent._output_verifier = StrictVerifier()

        result = await agent.run("Test goal")

        # The agent should detect bad output and trigger recovery
        assert len(result.incidents) >= 1

    @pytest.mark.asyncio
    async def test_goal_in_result(self):
        """Result preserves the goal string."""
        planner = FakePlanner([])
        executor = FakeExecutor({})
        orchestrator = FakeRecoveryOrchestrator()
        instrumentation = FakeInstrumentation()

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
        )

        result = await agent.run("My important goal")
        assert result.goal == "My important goal"

    @pytest.mark.asyncio
    async def test_instrumentation_records_events(self):
        """Instrumentation is called for each step."""
        steps = [
            Step(step_id="1", tool_name="ping", arguments={}, description="Ping"),
        ]
        planner = FakePlanner(steps)
        executor = FakeExecutor({
            "ping": StepResult(step=steps[0], success=True, output="pong", verdict=Verdict.SUCCESS),
        })
        orchestrator = FakeRecoveryOrchestrator()
        instrumentation = FakeInstrumentation()

        agent = SelfHealingAgent(
            planner=planner,
            executor=executor,
            recovery_orchestrator=orchestrator,
            instrumentation=instrumentation,
        )

        await agent.run("Test")

        # Instrumentation should have at least some traces or logs
        assert len(instrumentation.get_traces()) >= 1 or len(instrumentation.get_logs()) >= 1


class TestAgentResult:
    """Test the AgentResult model."""

    def test_empty_result(self):
        from neo_mcp.agent.orchestrator import AgentResult
        r = AgentResult(goal="test", step_results=[], incidents=[])
        assert r.goal == "test"
        assert len(r.step_results) == 0
        assert len(r.incidents) == 0
        assert r.success is True  # No steps = trivially successful

    def test_success_with_all_successful(self):
        from neo_mcp.agent.orchestrator import AgentResult
        s = Step(step_id="1", tool_name="t", arguments={})
        r = AgentResult(
            goal="test",
            step_results=[StepResult(step=s, success=True, output="ok", verdict=Verdict.SUCCESS)],
            incidents=[],
        )
        assert r.success is True

    def test_success_with_recovered(self):
        from neo_mcp.agent.orchestrator import AgentResult
        s = Step(step_id="1", tool_name="t", arguments={})
        r = AgentResult(
            goal="test",
            step_results=[StepResult(step=s, success=True, output="ok", verdict=Verdict.RECOVERED)],
            incidents=[],
        )
        assert r.success is True  # Recovered from failure

    def test_failure_with_unrecovered(self):
        from neo_mcp.agent.orchestrator import AgentResult
        s = Step(step_id="1", tool_name="t", arguments={})
        r = AgentResult(
            goal="test",
            step_results=[StepResult(step=s, success=False, output=None, error="fail",
                                    verdict=Verdict.FAILURE)],
            incidents=[],
        )
        assert r.success is False

    def test_mixed_results(self):
        from neo_mcp.agent.orchestrator import AgentResult
        s1 = Step(step_id="1", tool_name="a", arguments={})
        s2 = Step(step_id="2", tool_name="b", arguments={})
        r = AgentResult(
            goal="test",
            step_results=[
                StepResult(step=s1, success=True, output="ok", verdict=Verdict.SUCCESS),
                StepResult(step=s2, success=False, output=None, error="fail",
                          verdict=Verdict.FAILURE),
            ],
            incidents=[],
        )
        assert r.success is False  # Some steps failed