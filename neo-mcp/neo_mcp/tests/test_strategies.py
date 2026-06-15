"""Unit tests for all RecoveryStrategy implementations — no real API calls."""

import pytest

from neo_mcp.core.models import RecoveryAction, Step
from neo_mcp.recovery.strategies import (
    EscalateStrategy,
    ExponentialBackoffStrategy,
    FailStrategy,
    RepairAndRetryStrategy,
)


class TestExponentialBackoffStrategy:
    """Test ExponentialBackoffStrategy — RETRY action with backoff delay."""

    def setup_method(self):
        self.strategy = ExponentialBackoffStrategy(base_delay=0.01, max_delay=0.1)
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={"arg1": "value1"},
            description="Test step",
        )

    def test_get_action_returns_retry(self):
        assert self.strategy.get_action() == RecoveryAction.RETRY

    @pytest.mark.asyncio
    async def test_apply_returns_step_with_same_args(self):
        result = await self.strategy.apply(
            step=self.step,
            error_message="Some error",
            attempt_number=2,
        )
        assert result is not None
        assert result.step_id == "test_1"
        assert result.tool_name == "test_tool"
        assert result.arguments == {"arg1": "value1"}

    @pytest.mark.asyncio
    async def test_apply_increases_delay_with_attempts(self):
        t1_result = await self.strategy.apply(self.step, "err", 1)
        t2_result = await self.strategy.apply(self.step, "err", 2)
        assert t1_result is not None
        assert t2_result is not None


class TestRepairAndRetryStrategy:
    """Test RepairAndRetryStrategy — REPAIR_AND_RETRY action."""

    def setup_method(self):
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={"arg1": "value1"},
            description="Test step",
        )

    def test_get_action_returns_repair_and_retry(self):
        strategy = RepairAndRetryStrategy(None)
        assert strategy.get_action() == RecoveryAction.REPAIR_AND_RETRY

    @pytest.mark.asyncio
    async def test_apply_with_null_repairer_returns_step(self):
        from neo_mcp.recovery.argument_repairer import NullArgumentRepairer
        strategy = RepairAndRetryStrategy(NullArgumentRepairer())
        result = await strategy.apply(
            step=self.step,
            error_message="schema violation",
            attempt_number=1,
        )
        assert result is not None
        assert result.arguments == {"arg1": "value1"}

    @pytest.mark.asyncio
    async def test_apply_with_repairing_repairer_fixes_args(self):
        class FixingRepairer:
            async def repair_arguments(self, tool_name, arguments, error_message, tool_schema=None):
                return {**arguments, "fixed": True}

        strategy = RepairAndRetryStrategy(FixingRepairer())
        result = await strategy.apply(
            step=self.step,
            error_message="bad args",
            attempt_number=1,
        )
        assert result is not None
        assert result.arguments == {"arg1": "value1", "fixed": True}

    @pytest.mark.asyncio
    async def test_apply_with_failing_repairer_returns_original_args(self):
        class FailingRepairer:
            async def repair_arguments(self, tool_name, arguments, error_message, tool_schema=None):
                return arguments  # Returns unchanged

        strategy = RepairAndRetryStrategy(FailingRepairer())
        result = await strategy.apply(
            step=self.step,
            error_message="error",
            attempt_number=1,
        )
        assert result is not None
        assert result.arguments == {"arg1": "value1"}


class TestEscalateStrategy:
    """Test EscalateStrategy — ESCALATE action, returns None."""

    def setup_method(self):
        self.strategy = EscalateStrategy()
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={},
            description="Test step",
        )

    def test_get_action_returns_escalate(self):
        assert self.strategy.get_action() == RecoveryAction.ESCALATE

    @pytest.mark.asyncio
    async def test_apply_returns_none(self):
        result = await self.strategy.apply(
            step=self.step,
            error_message="downstream error",
            attempt_number=1,
        )
        assert result is None


class TestFailStrategy:
    """Test FailStrategy — FAIL action, returns None."""

    def setup_method(self):
        self.strategy = FailStrategy()
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={},
            description="Test step",
        )

    def test_get_action_returns_fail(self):
        assert self.strategy.get_action() == RecoveryAction.FAIL

    @pytest.mark.asyncio
    async def test_apply_returns_none(self):
        result = await self.strategy.apply(
            step=self.step,
            error_message="permanent error",
            attempt_number=1,
        )
        assert result is None