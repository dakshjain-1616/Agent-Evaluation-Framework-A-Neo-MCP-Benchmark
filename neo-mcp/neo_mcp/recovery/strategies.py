"""Recovery strategies for the self-healing agent platform.

Each strategy implements the RecoveryStrategy interface and handles a specific
recovery action flow.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, Optional

from neo_mcp.core.interfaces import (
    ArgumentRepairer,
    OutputVerifier,
    RecoveryStrategy,
)
from neo_mcp.core.models import RecoveryAction, Step


class ExponentialBackoffStrategy(RecoveryStrategy):
    """RETRY strategy with exponential backoff and jitter.

    Waits: base_delay * (2 ^ (attempt - 1)) + jitter, then returns the step
    unchanged for re-execution.
    """

    def __init__(self, base_delay: float = 1.0, max_delay: float = 30.0) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay

    def get_action(self) -> RecoveryAction:
        return RecoveryAction.RETRY

    async def apply(
        self,
        step: Step,
        error_message: str,
        attempt_number: int,
        **kwargs: Any,
    ) -> Optional[Step]:
        """Wait with exponential backoff, then return step for retry."""
        delay = min(
            self._base_delay * (2 ** (attempt_number - 1)),
            self._max_delay,
        )
        # Add jitter: ±25%
        jitter = random.uniform(-0.25 * delay, 0.25 * delay)
        total_delay = max(0.1, delay + jitter)

        await asyncio.sleep(total_delay)
        return step  # Return unchanged step for re-execution


class RepairAndRetryStrategy(RecoveryStrategy):
    """REPAIR_AND_RETRY strategy — repairs arguments via ArgumentRepairer,
    then returns a modified step with the repaired arguments."""

    def __init__(self, repairer: ArgumentRepairer) -> None:
        self._repairer = repairer

    def get_action(self) -> RecoveryAction:
        return RecoveryAction.REPAIR_AND_RETRY

    async def apply(
        self,
        step: Step,
        error_message: str,
        attempt_number: int,
        **kwargs: Any,
    ) -> Optional[Step]:
        """Repair arguments and return modified step for retry."""
        tool_schema = kwargs.get("tool_schema")

        repaired_args = await self._repairer.repair_arguments(
            tool_name=step.tool_name,
            arguments=step.arguments,
            error_message=error_message,
            tool_schema=tool_schema,
        )

        # Return a new step with repaired arguments
        return Step(
            step_id=step.step_id,
            tool_name=step.tool_name,
            arguments=repaired_args,
            description=step.description,
            max_retries=step.max_retries,
            timeout_seconds=step.timeout_seconds,
        )


class EscalateStrategy(RecoveryStrategy):
    """ESCALATE strategy — logs the failure and signals escalation."""

    def get_action(self) -> RecoveryAction:
        return RecoveryAction.ESCALATE

    async def apply(
        self,
        step: Step,
        error_message: str,
        attempt_number: int,
        **kwargs: Any,
    ) -> Optional[Step]:
        """Escalate — return None to signal that recovery cannot proceed."""
        return None  # None signals escalation / halt


class FailStrategy(RecoveryStrategy):
    """FAIL strategy — signals that the step should fail gracefully."""

    def get_action(self) -> RecoveryAction:
        return RecoveryAction.FAIL

    async def apply(
        self,
        step: Step,
        error_message: str,
        attempt_number: int,
        **kwargs: Any,
    ) -> Optional[Step]:
        """Fail — return None to indicate no recovery possible."""
        return None