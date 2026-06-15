"""Core data models for the neo-mcp self-healing agent platform."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class FailureCategory(str, Enum):
    """Categorization of a failure for recovery strategy selection."""

    TRANSIENT = "TRANSIENT"
    """Temporary failure that may succeed on retry (rate limit, timeout, network glitch)."""

    PERMANENT_BAD_ARGS = "PERMANENT_BAD_ARGS"
    """Invalid arguments passed to a tool or function (schema violation, type error)."""

    PERMANENT_AUTH = "PERMANENT_AUTH"
    """Authentication or authorization failure (401, 403, invalid API key)."""

    PERMANENT_DOWNSTREAM = "PERMANENT_DOWNSTREAM"
    """Downstream service error that cannot be resolved by retry/repair."""

    UNKNOWN = "UNKNOWN"
    """Unclassifiable failure — treat as permanent and escalate."""


class RecoveryAction(str, Enum):
    """Action to take for a given failure."""

    RETRY = "RETRY"
    """Retry the step with exponential backoff (transient failures)."""

    REPAIR_AND_RETRY = "REPAIR_AND_RETRY"
    """Repair tool arguments, then retry (bad args failures)."""

    ESCALATE = "ESCALATE"
    """Escalate the failure — log incident and halt or skip the step."""

    FAIL = "FAIL"
    """Fail the step gracefully with the original error recorded."""


class Verdict(str, Enum):
    """Outcome of a step or recovery attempt."""

    SUCCESS = "SUCCESS"
    """Step completed successfully."""

    FAILURE = "FAILURE"
    """Step failed and recovery did not resolve it."""

    RECOVERED = "RECOVERED"
    """Step initially failed but was recovered via retry/repair."""

    ESCALATED = "ESCALATED"
    """Step failure was escalated for manual intervention."""

    SKIPPED = "SKIPPED"
    """Step was skipped due to prior escalation."""


@dataclass
class Step:
    """A single step within a plan."""

    step_id: str
    """Unique identifier for the step."""

    tool_name: str
    """Name of the tool to execute."""

    arguments: Dict[str, Any]
    """Arguments to pass to the tool."""

    description: str = ""
    """Human-readable description of what this step does."""

    max_retries: int = 3
    """Maximum number of retry attempts for this step."""

    timeout_seconds: int = 30
    """Timeout in seconds for tool execution."""


@dataclass
class Plan:
    """A sequence of steps to achieve a goal."""

    goal: str
    """The original goal that this plan is for."""

    steps: List[Step]
    """Ordered list of steps to execute."""

    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unique identifier for this plan."""

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When this plan was created."""

    def __len__(self) -> int:
        return len(self.steps)

    def __getitem__(self, index: int) -> Step:
        return self.steps[index]


@dataclass
class StepResult:
    """The result of executing a single step."""

    step: Step
    """The step that was executed."""

    success: bool
    """Whether the step completed successfully."""

    output: Optional[Any] = None
    """Tool output if successful (after verification)."""

    error: Optional[str] = None
    """Error message if the step failed."""

    exception_type: Optional[str] = None
    """Fully qualified exception class name if applicable."""

    duration_ms: float = 0.0
    """Execution duration in milliseconds."""

    attempts: int = 1
    """Number of attempts made (including retries)."""

    verdict: Verdict = Verdict.SUCCESS
    """Final verdict after any recovery attempts."""

    recovered: bool = False
    """Whether recovery was successfully applied."""


@dataclass
class FailureClassification:
    """Output of classifying a failure."""

    category: FailureCategory
    """The classified failure category."""

    action: RecoveryAction
    """The recommended recovery action."""

    confidence: float = 1.0
    """Confidence in the classification (0.0 to 1.0)."""

    details: Optional[str] = None
    """Additional context about the classification."""

    requires_repair: bool = False
    """Whether argument repair should be attempted."""

    is_transient: bool = False
    """Whether the failure is likely transient."""


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt."""

    attempt_number: int
    """Which attempt this is (1-based)."""

    action: RecoveryAction
    """The recovery action taken."""

    before_state: Optional[Dict[str, Any]] = None
    """State before recovery (original args, etc.)."""

    after_state: Optional[Dict[str, Any]] = None
    """State after recovery (repaired args, etc.)."""

    duration_ms: float = 0.0
    """How long the recovery attempt took."""

    result: Optional[StepResult] = None
    """The result after this recovery attempt."""

    success: bool = False
    """Whether this attempt resolved the failure."""


@dataclass
class IncidentRecord:
    """Complete record of a failure and its recovery chain."""

    incident_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unique identifier for this incident."""

    step: Optional[Step] = None
    """The step that failed."""

    original_error: Optional[str] = None
    """The original error message."""

    classification: Optional[FailureClassification] = None
    """How the failure was classified."""

    attempts: List[RecoveryAttempt] = field(default_factory=list)
    """Ordered list of recovery attempts made."""

    final_verdict: Verdict = Verdict.FAILURE
    """Final outcome after all recovery attempts."""

    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """When the incident occurred."""

    resolved: bool = False
    """Whether the incident was fully resolved."""