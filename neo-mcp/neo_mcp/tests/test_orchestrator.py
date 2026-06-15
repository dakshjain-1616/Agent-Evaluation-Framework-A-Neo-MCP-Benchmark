"""Unit tests for RecoveryOrchestrator — no real API calls."""

import pytest

from neo_mcp.core.models import (
    FailureCategory,
    FailureClassification,
    RecoveryAction,
    Step,
    StepResult,
    Verdict,
)
from neo_mcp.recovery.orchestrator import RecoveryOrchestrator


class FakeClassifier:
    """Returns a predefined classification."""

    def __init__(self, classification):
        self.classification = classification

    def classify(self, error_message, exception_type):
        return self.classification


class FakeExecutor:
    """Returns a predefined StepResult."""

    def __init__(self, result_fn=None):
        # result_fn(step) -> StepResult
        self._result_fn = result_fn or (lambda s: StepResult(
            step=s, success=True, output="ok", verdict=Verdict.SUCCESS,
        ))

    async def execute_step(self, step):
        return self._result_fn(step)


class FakeVerifier:
    def __init__(self, result=True):
        self._result = result

    def verify(self, output, step, output_schema=None):
        return self._result


class TestRecoveryOrchestrator:
    """Test orchestrator state machine."""

    @pytest.mark.asyncio
    async def test_transient_retry_then_success(self):
        """TRANSIENT -> RETRY -> succeeds on 2nd attempt -> RECOVERED."""
        call_count = [0]

        def executor_fn(step):
            call_count[0] += 1
            if call_count[0] == 1:
                return StepResult(
                    step=step, success=False, output=None,
                    error="rate limit exceeded", exception_type="RuntimeError",
                    verdict=Verdict.FAILURE,
                )
            return StepResult(
                step=step, success=True, output="success", verdict=Verdict.SUCCESS,
            )

        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.TRANSIENT,
            action=RecoveryAction.RETRY,
            is_transient=True,
            requires_repair=False,
            details="rate limit",
        ))

        strategies = {
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(True),
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="test_tool", arguments={}, description="Test")
        incident = await orchestrator.recover(
            step=step,
            initial_error="rate limit exceeded",
            exception_type="RuntimeError",
        )

        assert incident.resolved is True
        assert incident.final_verdict == Verdict.RECOVERED
        assert len(incident.attempts) >= 1
        assert call_count[0] == 2  # First failed, second succeeded

    @pytest.mark.asyncio
    async def test_permanent_auth_immediate_fail(self):
        """PERMANENT_AUTH -> FAIL -> never executes."""
        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.PERMANENT_AUTH,
            action=RecoveryAction.FAIL,
            is_transient=False,
            requires_repair=False,
            details="auth error",
        ))

        strategies = {
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        executed = [False]

        def executor_fn(step):
            executed[0] = True
            return StepResult(step=step, success=True, output="ok", verdict=Verdict.SUCCESS)

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(True),
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="test", arguments={}, description="Test")
        incident = await orchestrator.recover(step=step, initial_error="401 Unauthorized", exception_type="RuntimeError")

        # FAIL strategy returns None, orchestrator breaks without setting resolved=True
        assert incident.resolved is False
        assert incident.final_verdict == Verdict.FAILURE
        assert executed[0] is False  # Never executed

    @pytest.mark.asyncio
    async def test_all_attempts_fail(self):
        """All retry attempts fail -> FAILURE verdict."""
        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.TRANSIENT,
            action=RecoveryAction.RETRY,
            is_transient=True,
            requires_repair=False,
            details="transient",
        ))

        strategies = {
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        call_count = [0]

        def executor_fn(step):
            call_count[0] += 1
            return StepResult(
                step=step, success=False, output=None,
                error="timeout", exception_type="TimeoutError",
                verdict=Verdict.FAILURE,
            )

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(True),
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="test", arguments={}, description="Test")
        incident = await orchestrator.recover(step=step, initial_error="timeout", exception_type="TimeoutError")

        # All attempts exhausted, never recovered — resolved stays False
        assert incident.resolved is False
        assert incident.final_verdict == Verdict.FAILURE
        assert call_count[0] == 3  # All 3 attempts exhausted

    @pytest.mark.asyncio
    async def test_downstream_escalates(self):
        """PERMANENT_DOWNSTREAM -> ESCALATE -> never retries."""
        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.PERMANENT_DOWNSTREAM,
            action=RecoveryAction.ESCALATE,
            is_transient=False,
            requires_repair=False,
            details="downstream 503",
        ))

        strategies = {
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        executed = [False]

        def executor_fn(step):
            executed[0] = True
            return StepResult(step=step, success=True, output="ok", verdict=Verdict.SUCCESS)

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(True),
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="test", arguments={}, description="Test")
        incident = await orchestrator.recover(step=step, initial_error="503 Service Unavailable", exception_type="RuntimeError")

        # ESCALATE strategy returns None, orchestrator breaks without setting resolved=True
        assert incident.resolved is False
        assert incident.final_verdict == Verdict.ESCALATED
        assert executed[0] is False

    @pytest.mark.asyncio
    async def test_output_verification_failure_triggers_retry(self):
        """Successfully executed but output verification fails -> retry."""
        call_count = [0]

        def executor_fn(step):
            call_count[0] += 1
            return StepResult(step=step, success=True, output="data", verdict=Verdict.SUCCESS)

        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.TRANSIENT,
            action=RecoveryAction.RETRY,
            is_transient=True,
            requires_repair=False,
            details="output verification failed",
        ))

        strategies = {
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(False),  # Verification always fails
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="validate_report", arguments={}, description="Validate")
        incident = await orchestrator.recover(
            step=step,
            initial_error="Output verification failed for tool 'validate_report'",
            exception_type="OutputVerificationError",
        )

        # All attempts exhausted due to verification failure — resolved stays False
        assert incident.resolved is False
        assert call_count[0] == 3  # All attempts exhausted due to verification failure

    @pytest.mark.asyncio
    async def test_incident_has_attempt_details(self):
        """Incident record contains all attempt details."""
        call_count = [0]

        def executor_fn(step):
            call_count[0] += 1
            if call_count[0] == 1:
                return StepResult(
                    step=step, success=False, output=None,
                    error="timeout", exception_type="TimeoutError",
                    verdict=Verdict.FAILURE,
                )
            return StepResult(
                step=step, success=True, output="ok", verdict=Verdict.SUCCESS,
            )

        classifier = FakeClassifier(FailureClassification(
            category=FailureCategory.TRANSIENT,
            action=RecoveryAction.RETRY,
            is_transient=True,
            requires_repair=False,
            details="timeout",
        ))

        strategies = {
            RecoveryAction.RETRY: FakeStrategy(RecoveryAction.RETRY, returns_step=True),
            RecoveryAction.FAIL: FakeStrategy(RecoveryAction.FAIL, returns_step=False),
            RecoveryAction.ESCALATE: FakeStrategy(RecoveryAction.ESCALATE, returns_step=False),
            RecoveryAction.REPAIR_AND_RETRY: FakeStrategy(RecoveryAction.REPAIR_AND_RETRY, returns_step=True),
        }

        orchestrator = RecoveryOrchestrator(
            classifier=classifier,
            strategies=strategies,
            executor=FakeExecutor(executor_fn),
            output_verifier=FakeVerifier(True),
            max_attempts=3,
        )

        step = Step(step_id="s1", tool_name="test", arguments={}, description="Test")
        incident = await orchestrator.recover(step=step, initial_error="timeout", exception_type="TimeoutError")

        assert incident.final_verdict == Verdict.RECOVERED
        assert len(incident.attempts) == 2  # Failed once, succeeded once
        assert incident.attempts[0].success is False
        assert incident.attempts[1].success is True


class FakeStrategy:
    """Fake recovery strategy for testing."""

    def __init__(self, action, returns_step=True):
        self._action = action
        self._returns_step = returns_step

    def get_action(self):
        return self._action

    async def apply(self, step, error_message, attempt_number, **kwargs):
        if self._returns_step:
            return step
        return None