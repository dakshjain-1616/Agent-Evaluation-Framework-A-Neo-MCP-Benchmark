"""Eval observability — composes with existing instrumentation and failure classifiers.

Provides EvalInstrumentation that wraps ConsoleInstrumentation to add evaluation-specific
logging and metrics. Also provides EVAL_FAILURE_PATTERNS demonstrating how to extend
RuleBasedFailureClassifier via composition (not inheritance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neo_mcp.core.models import FailureCategory
from neo_mcp.observability.instrumentation import ConsoleInstrumentation
from neo_mcp.recovery.failure_classifier import RuleBasedFailureClassifier


@dataclass
class EvalEvent:
    """A structured event recorded during evaluation runs.

    Attributes:
        event_type: Type of event (e.g., 'run_start', 'case_start', 'case_complete', 'error').
        case_id: The evaluation case ID, if applicable.
        metric_name: The metric being evaluated, if applicable.
        score: The score recorded, if applicable.
        details: Additional event-specific data.
        timestamp: Event timestamp (ISO format).
    """

    event_type: str = ""
    case_id: str = ""
    metric_name: str = ""
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


class EvalInstrumentation:
    """Evaluation-specific instrumentation that COMPOSES with ConsoleInstrumentation.

    This is NOT a fork or subclass of ConsoleInstrumentation — it composes with it.
    All evaluation events are logged both to the underlying ConsoleInstrumentation
    and to a local eval_events list for structured access.

    Usage:
        base_instr = ConsoleInstrumentation()
        eval_instr = EvalInstrumentation(instrumentation=base_instr)
        eval_instr.record_eval_event(event_type="run_start")
    """

    def __init__(
        self,
        instrumentation: Optional[ConsoleInstrumentation] = None,
    ) -> None:
        self._instrumentation = instrumentation or ConsoleInstrumentation()
        self._eval_events: List[EvalEvent] = []

    @property
    def instrumentation(self) -> ConsoleInstrumentation:
        """Access the underlying ConsoleInstrumentation."""
        return self._instrumentation

    def record_eval_event(
        self,
        event_type: str,
        case_id: str = "",
        metric_name: str = "",
        score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an evaluation event.

        The event is stored in the internal eval_events list AND logged to the
        underlying ConsoleInstrumentation.
        """
        from datetime import datetime, timezone

        event = EvalEvent(
            event_type=event_type,
            case_id=case_id,
            metric_name=metric_name,
            score=score,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._eval_events.append(event)
        self._instrumentation.log(
            level="INFO",
            message=f"[EVAL] {event_type} | case={case_id} metric={metric_name} score={score}",
        )
        if metric_name:
            self._instrumentation.increment(f"eval.metric.{metric_name}")
        self._instrumentation.increment(f"eval.event.{event_type}")

    def get_eval_events(
        self,
        event_type: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> List[EvalEvent]:
        """Get filtered evaluation events.

        Args:
            event_type: Optional filter by event type.
            case_id: Optional filter by case ID.

        Returns:
            Filtered list of EvalEvent objects.
        """
        events = self._eval_events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if case_id:
            events = [e for e in events if e.case_id == case_id]
        return events

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of evaluation metrics from the underlying instrumentation."""
        return self._instrumentation.get_metrics_snapshot()

    def clear(self) -> None:
        """Clear all recorded events and underlying instrumentation state."""
        self._eval_events.clear()
        self._instrumentation.clear()


# ----- Failure pattern extension via composition -----

# EVAL_FAILURE_PATTERNS demonstrates how to extend RuleBasedFailureClassifier
# by composing patterns, NOT by subclassing or modifying the original class.
#
# To use with RuleBasedFailureClassifier:
#   classifier = RuleBasedFailureClassifier(patterns=EVAL_FAILURE_PATTERNS)
#
# These patterns are designed to catch evaluation-specific failure modes
# (e.g., empty responses, timeouts, tool call failures, malformed output).

EVAL_FAILURE_PATTERNS: List[Dict[str, Any]] = [
    {
        "pattern": r"(?i)\berror\b.*\bevaluation\b",
        "category": "EVAL_ERROR",
        "subtype": "general_eval_error",
        "description": "Generic evaluation error",
    },
    {
        "pattern": r"(?i)\btimeout\b",
        "category": "EVAL_TIMEOUT",
        "subtype": "execution_timeout",
        "description": "Evaluation case timed out",
    },
    {
        "pattern": r"(?i)\bempty response\b",
        "category": "EVAL_EMPTY_RESPONSE",
        "subtype": "no_output",
        "description": "Agent produced empty response",
    },
    {
        "pattern": r"(?i)\btool call failed\b",
        "category": "EVAL_TOOL_FAILURE",
        "subtype": "tool_execution_error",
        "description": "Tool call failed during evaluation",
    },
    {
        "pattern": r"(?i)\bmalformed output\b",
        "category": "EVAL_MALFORMED_OUTPUT",
        "subtype": "output_parse_error",
        "description": "Output could not be parsed correctly",
    },
    {
        "pattern": r"(?i)\bunexpected exception\b",
        "category": "EVAL_UNEXPECTED_ERROR",
        "subtype": "runtime_exception",
        "description": "Unexpected exception during evaluation",
    },
    {
        "pattern": r"(?i)\bnot found\b",
        "category": "EVAL_NOT_FOUND",
        "subtype": "resource_missing",
        "description": "Required resource not found during evaluation",
    },
    {
        "pattern": r"(?i)\binvalid\b.*\bresult\b",
        "category": "EVAL_INVALID_RESULT",
        "subtype": "invalid_output",
        "description": "Agent returned invalid result",
    },
]


def _make_category(cat_str: str) -> FailureCategory:
    """Create a FailureCategory value from a string, supporting arbitrary categories.

    For known FailureCategory values, returns the enum member directly.
    For custom categories (e.g., 'CUSTOM', 'EVAL_ERROR'), dynamically creates
    a compatible enum member so that `.value` returns the expected string.

    Args:
        cat_str: The category string (e.g., 'TRANSIENT', 'CUSTOM', 'EVAL_ERROR').

    Returns:
        A FailureCategory-compatible enum value.
    """
    try:
        return FailureCategory(cat_str)
    except ValueError:
        # Dynamically create a compatible enum member for arbitrary category strings.
        # Since FailureCategory is (str, Enum), we must use str.__new__().
        member = str.__new__(FailureCategory)
        member._name_ = cat_str.upper().replace(" ", "_")
        member._value_ = cat_str
        return member


def extend_failure_classifier(
    classifier: RuleBasedFailureClassifier,
    extra_patterns: Optional[List[Dict[str, Any]]] = None,
) -> RuleBasedFailureClassifier:
    """Extend a RuleBasedFailureClassifier with evaluation-specific patterns.

    This function demonstrates COMPOSITION over inheritance. It takes an existing
    RuleBasedFailureClassifier and demonstrates how additional *rules* can be
    composed alongside the original classifier's rules.

    Since RuleBasedFailureClassifier builds its rules in __init__ and does not
    accept external patterns, this function wraps classification by first trying
    the base classifier, then falling back to evaluation patterns if no match.

    Args:
        classifier: An existing RuleBasedFailureClassifier instance.
        extra_patterns: Additional patterns to use. If None, uses EVAL_FAILURE_PATTERNS.

    Returns:
        A wrapper that tries base rules first, then eval patterns.
    """
    import re

    from neo_mcp.core.models import FailureCategory, FailureClassification, RecoveryAction

    patterns_to_use = extra_patterns or EVAL_FAILURE_PATTERNS

    class CompositeFailureClassifier(RuleBasedFailureClassifier):
        """A composite classifier that tries base rules then eval patterns."""

        def classify(
            self,
            error_message: str,
            exception_type: Optional[str] = None,
        ) -> FailureClassification:
            # Try base classifier first
            result = classifier.classify(error_message, exception_type)
            # If base didn't find a match (UNKNOWN), try eval patterns
            if result.category == FailureCategory.UNKNOWN:
                for pattern in patterns_to_use:
                    if re.search(pattern["pattern"], error_message or ""):
                        return FailureClassification(
                            category=_make_category(pattern["category"]),
                            action=RecoveryAction.FAIL,
                            details=pattern.get("description", "Matched eval pattern"),
                            is_transient=False,
                            requires_repair=False,
                        )
            return result

    return CompositeFailureClassifier()