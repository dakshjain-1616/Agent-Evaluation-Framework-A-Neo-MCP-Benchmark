"""Abstract interfaces for the neo-mcp self-healing agent platform.

All components are defined behind clean abstract base classes so they can be
independently implemented, tested, and swapped.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from neo_mcp.core.models import (
    FailureClassification,
    IncidentRecord,
    Plan,
    RecoveryAction,
    Step,
    StepResult,
)


class Planner(abc.ABC):
    """Generates a plan (sequence of steps) from a goal.

    Implementations: LLMPlanner (uses Claude), FixedPlanner (testing).
    """

    @abc.abstractmethod
    async def plan(self, goal: str, tool_descriptions: List[Dict[str, Any]]) -> Plan:
        """Generate a plan to achieve the given goal.

        Args:
            goal: The objective the agent should accomplish.
            tool_descriptions: List of available tool metadata dicts.

        Returns:
            A Plan with ordered steps.

        Raises:
            PlanningError: If planning fails.
        """
        ...


class Executor(abc.ABC):
    """Executes a single step by dispatching to the appropriate tool."""

    @abc.abstractmethod
    async def execute_step(self, step: Step) -> StepResult:
        """Execute a single step and return its result.

        Args:
            step: The step to execute.

        Returns:
            StepResult capturing success/failure, output, error, and duration.
        """
        ...


class FailureClassifier(abc.ABC):
    """Classifies a failure (error message + exception type) into a category."""

    @abc.abstractmethod
    def classify(
        self,
        error_message: str,
        exception_type: Optional[str] = None,
    ) -> FailureClassification:
        """Classify the failure and recommend a recovery action.

        Args:
            error_message: The error message from the failed execution.
            exception_type: Optional fully-qualified exception class name.

        Returns:
            A FailureClassification with category, action, and metadata.
        """
        ...


class ArgumentRepairer(abc.ABC):
    """Repairs malformed tool arguments for re-invocation."""

    @abc.abstractmethod
    async def repair_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_message: str,
        tool_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Repair arguments that caused a tool failure.

        Args:
            tool_name: Name of the tool that failed.
            arguments: The original (malformed) arguments.
            error_message: The error that occurred.
            tool_schema: Optional JSON schema for the tool's input.

        Returns:
            Repaired arguments as a dict.
        """
        ...


class OutputVerifier(abc.ABC):
    """Verifies that tool output meets expected criteria."""

    @abc.abstractmethod
    def verify(
        self,
        output: Any,
        step: Step,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Verify tool output against expected schema or rules.

        Args:
            output: The tool output to verify.
            step: The step that produced this output.
            output_schema: Optional JSON schema for expected output.

        Returns:
            True if output is valid, False otherwise.
        """
        ...


class RecoveryStrategy(abc.ABC):
    """Strategy for recovering from a specific failure category."""

    @abc.abstractmethod
    def get_action(self) -> RecoveryAction:
        """Return the recovery action this strategy implements."""
        ...

    @abc.abstractmethod
    async def apply(
        self,
        step: Step,
        error_message: str,
        attempt_number: int,
        **kwargs: Any,
    ) -> Optional[Step]:
        """Apply the recovery strategy and return a (possibly modified) step.

        Args:
            step: The original step that failed.
            error_message: The error message.
            attempt_number: Current attempt number (1-based).
            **kwargs: Additional context (classification, repairer, verifier, etc.).

        Returns:
            A modified Step to retry, or None if recovery fails.
        """
        ...


class LLMProvider(abc.ABC):
    """Abstract interface for LLM access.

    Implementations: AnthropicLLMProvider, OpenRouterLLMProvider, etc.
    """

    @abc.abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Generate a response from the LLM.

        Args:
            system_prompt: System-level instructions.
            user_prompt: The user's message / task description.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            The generated text response.

        Raises:
            ProviderError: If the LLM call fails.
        """
        ...


class Instrumentation(abc.ABC):
    """Observability interface for logging, metrics, and tracing."""

    @abc.abstractmethod
    def log(self, level: str, message: str, **context: Any) -> None:
        """Emit a structured log entry.

        Args:
            level: Log level (DEBUG, INFO, WARN, ERROR).
            message: Log message.
            **context: Additional structured context fields.
        """
        ...

    @abc.abstractmethod
    def increment(
        self, metric_name: str, value: int = 1, **tags: Any
    ) -> None:
        """Increment a counter metric.

        Args:
            metric_name: Name of the metric.
            value: Value to increment by (default 1).
            **tags: Tags/labels for the metric.
        """
        ...

    @abc.abstractmethod
    def record_trace(
        self,
        step_id: str,
        event: str,
        duration_ms: float,
        **attributes: Any,
    ) -> None:
        """Record a trace event for a step.

        Args:
            step_id: The step or span identifier.
            event: Event name (e.g., 'execute', 'classify', 'retry').
            duration_ms: Duration of the event in milliseconds.
            **attributes: Additional attributes for the trace span.
        """
        ...

    @abc.abstractmethod
    def get_metrics_snapshot(self) -> Dict[str, int]:
        """Return a snapshot of all accumulated metrics counters.

        Returns:
            Dict mapping metric names to their current counts.
        """
        ...

    @abc.abstractmethod
    def get_traces(self) -> List[Dict[str, Any]]:
        """Return all recorded traces.

        Returns:
            List of trace event dicts.
        """
        ...