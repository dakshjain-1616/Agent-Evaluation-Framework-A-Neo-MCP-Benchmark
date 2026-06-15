"""Unit tests for core data models — all instantiable and well-formed."""

from neo_mcp.core.models import (
    FailureCategory,
    FailureClassification,
    IncidentRecord,
    Plan,
    RecoveryAction,
    RecoveryAttempt,
    Step,
    StepResult,
    Verdict,
)


class TestStep:
    def test_create_minimal(self):
        s = Step(step_id="s1", tool_name="test_tool", arguments={})
        assert s.step_id == "s1"
        assert s.tool_name == "test_tool"
        assert s.arguments == {}
        assert s.description == ""  # default
        assert s.max_retries == 3  # default
        assert s.timeout_seconds == 30  # default

    def test_create_full(self):
        s = Step(
            step_id="s1",
            tool_name="echo",
            arguments={"msg": "hello"},
            description="Echo step",
            max_retries=5,
            timeout_seconds=60,
        )
        assert s.description == "Echo step"
        assert s.max_retries == 5
        assert s.timeout_seconds == 60


class TestPlan:
    def test_create_with_steps(self):
        steps = [
            Step(step_id="1", tool_name="a", arguments={}),
            Step(step_id="2", tool_name="b", arguments={}),
        ]
        plan = Plan(goal="Test goal", steps=steps)
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool_name == "a"

    def test_len(self):
        plan = Plan(goal="g", steps=[Step(step_id="1", tool_name="t", arguments={})])
        assert len(plan) == 1

    def test_empty_plan(self):
        plan = Plan(goal="g", steps=[])
        assert len(plan) == 0


class TestStepResult:
    def test_success_result(self):
        s = Step(step_id="1", tool_name="t", arguments={})
        r = StepResult(step=s, success=True, output="done", verdict=Verdict.SUCCESS)
        assert r.success is True
        assert r.output == "done"
        assert r.error is None
        assert r.verdict == Verdict.SUCCESS

    def test_failure_result(self):
        s = Step(step_id="1", tool_name="t", arguments={})
        r = StepResult(
            step=s, success=False, output=None,
            error="rate limit", exception_type="RuntimeError",
            attempts=2, verdict=Verdict.RECOVERED,
        )
        assert r.success is False
        assert r.error == "rate limit"
        assert r.exception_type == "RuntimeError"
        assert r.attempts == 2
        assert r.verdict == Verdict.RECOVERED


class TestFailureCategory:
    def test_values(self):
        assert FailureCategory.TRANSIENT.value == "TRANSIENT"
        assert FailureCategory.PERMANENT_BAD_ARGS.value == "PERMANENT_BAD_ARGS"
        assert FailureCategory.PERMANENT_AUTH.value == "PERMANENT_AUTH"
        assert FailureCategory.PERMANENT_DOWNSTREAM.value == "PERMANENT_DOWNSTREAM"
        assert FailureCategory.UNKNOWN.value == "UNKNOWN"

    def test_distinct(self):
        cats = list(FailureCategory)
        assert len(cats) == 5
        assert len({c.value for c in cats}) == 5


class TestFailureClassification:
    def test_create(self):
        fc = FailureClassification(
            category=FailureCategory.TRANSIENT,
            action=RecoveryAction.RETRY,
            is_transient=True,
            requires_repair=False,
            details="rate limit on API call",
        )
        assert fc.category == FailureCategory.TRANSIENT
        assert fc.action == RecoveryAction.RETRY
        assert fc.is_transient is True
        assert fc.requires_repair is False


class TestRecoveryAction:
    def test_values(self):
        assert RecoveryAction.RETRY.value == "RETRY"
        assert RecoveryAction.REPAIR_AND_RETRY.value == "REPAIR_AND_RETRY"
        assert RecoveryAction.ESCALATE.value == "ESCALATE"
        assert RecoveryAction.FAIL.value == "FAIL"

    def test_distinct(self):
        assert len(list(RecoveryAction)) == 4


class TestIncidentRecord:
    def test_create(self):
        s = Step(step_id="1", tool_name="t", arguments={})
        incident = IncidentRecord(
            step=s,
            original_error="timeout",
            classification=None,
            attempts=[],
            final_verdict=Verdict.RECOVERED,
            resolved=True,
        )
        assert incident.step is s
        assert incident.original_error == "timeout"
        assert incident.final_verdict == Verdict.RECOVERED
        assert incident.resolved is True

    def test_with_attempts(self):
        s = Step(step_id="1", tool_name="t", arguments={})
        attempts = [
            RecoveryAttempt(attempt_number=1, action=RecoveryAction.RETRY,
                          success=False, duration_ms=100),
            RecoveryAttempt(attempt_number=2, action=RecoveryAction.RETRY,
                          success=True, duration_ms=50),
        ]
        incident = IncidentRecord(
            step=s,
            original_error="timeout",
            classification=None,
            attempts=attempts,
            final_verdict=Verdict.RECOVERED,
            resolved=True,
        )
        assert len(incident.attempts) == 2
        assert incident.attempts[0].attempt_number == 1
        assert incident.attempts[0].action == RecoveryAction.RETRY
        assert incident.attempts[0].duration_ms == 100


class TestVerdict:
    def test_values(self):
        assert Verdict.SUCCESS.value == "SUCCESS"
        assert Verdict.RECOVERED.value == "RECOVERED"
        assert Verdict.FAILURE.value == "FAILURE"
        assert Verdict.ESCALATED.value == "ESCALATED"
        assert Verdict.SKIPPED.value == "SKIPPED"

    def test_distinct(self):
        assert len(list(Verdict)) == 5