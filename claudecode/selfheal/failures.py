"""Failure taxonomy and classification.

Self-healing starts with *understanding* a failure rather than blindly retrying
it. Everything downstream — whether to retry, whether to repair arguments,
whether to escalate — is driven by the :class:`FailureClass` assigned here.

The classifier is an interface (:class:`FailureClassifier`) so it can be swapped
for a smarter implementation (e.g. an LLM-backed classifier) without touching the
recovery machinery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol


class FailureClass(Enum):
    """Categories of failure, each with a default recovery disposition."""

    TRANSIENT = "transient"
    """A momentary fault (network blip, timeout, downstream hiccup). Retrying as-is
    is likely to succeed."""

    RATE_LIMITED = "rate_limited"
    """The dependency asked us to slow down. Retry, but only after a backoff."""

    INVALID_ARGUMENT = "invalid_argument"
    """The call was malformed. Retrying unchanged is pointless; the arguments must
    be repaired first."""

    RESOURCE_EXHAUSTED = "resource_exhausted"
    """Quota/budget/disk exhausted. Sometimes recoverable after backoff, often not."""

    NOT_FOUND = "not_found"
    """A referenced resource does not exist. Usually permanent for the given args."""

    PERMISSION = "permission"
    """Authn/authz failure. Not self-recoverable; must escalate."""

    UNAVAILABLE = "unavailable"
    """Dependency is down. Retrying with backoff may help if it recovers."""

    BAD_OUTPUT = "bad_output"
    """The call 'succeeded' but produced output that failed verification."""

    LOGIC = "logic"
    """A deterministic bug in the tool. Retrying will reproduce it; escalate."""

    UNKNOWN = "unknown"
    """Could not be classified. Treated conservatively (limited retries)."""

    @property
    def transient(self) -> bool:
        """Whether a plain retry has a reasonable chance of succeeding."""
        return self in {
            FailureClass.TRANSIENT,
            FailureClass.RATE_LIMITED,
            FailureClass.UNAVAILABLE,
        }

    @property
    def repairable(self) -> bool:
        """Whether repairing the call's arguments could change the outcome."""
        return self in {FailureClass.INVALID_ARGUMENT, FailureClass.BAD_OUTPUT}

    @property
    def needs_backoff(self) -> bool:
        """Whether retries should wait (vs. retry immediately)."""
        return self in {
            FailureClass.RATE_LIMITED,
            FailureClass.RESOURCE_EXHAUSTED,
            FailureClass.UNAVAILABLE,
        }

    @property
    def terminal(self) -> bool:
        """Whether the failure is fundamentally not self-recoverable."""
        return self in {
            FailureClass.PERMISSION,
            FailureClass.NOT_FOUND,
            FailureClass.LOGIC,
        }

    @property
    def retryable(self) -> bool:
        """Whether retrying *without changing the call* could help.

        True for transient/backoff classes, for ``BAD_OUTPUT`` (a re-run may
        produce different output, e.g. a nondeterministic model), and for
        ``UNKNOWN`` (retry conservatively, bounded by ``max_attempts``). False for
        ``INVALID_ARGUMENT``, which is deterministic — only repair can change it.
        """
        return (
            self.transient
            or self.needs_backoff
            or self in {FailureClass.BAD_OUTPUT, FailureClass.UNKNOWN}
        )


@dataclass(frozen=True)
class Failure:
    """A classified failure with the context needed to drive recovery."""

    failure_class: FailureClass
    message: str
    tool: str
    attempt: int
    exception: BaseException | None = None
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def transient(self) -> bool:
        return self.failure_class.transient

    @property
    def repairable(self) -> bool:
        return self.failure_class.repairable

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.failure_class.value}] {self.tool}#{self.attempt}: {self.message}"


# ---------------------------------------------------------------------------
# Typed errors that tools may raise to declare their failure class explicitly.
# Tools are *not* required to use these — the heuristic classifier handles plain
# exceptions too — but raising them removes all ambiguity.
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base class for errors that carry a known :class:`FailureClass`."""

    failure_class: FailureClass = FailureClass.UNKNOWN


class TransientError(ToolError):
    failure_class = FailureClass.TRANSIENT


class RateLimitError(ToolError):
    failure_class = FailureClass.RATE_LIMITED


class InvalidArgumentError(ToolError):
    failure_class = FailureClass.INVALID_ARGUMENT


class ResourceExhaustedError(ToolError):
    failure_class = FailureClass.RESOURCE_EXHAUSTED


class NotFoundError(ToolError):
    failure_class = FailureClass.NOT_FOUND


class PermissionDeniedError(ToolError):
    failure_class = FailureClass.PERMISSION


class UnavailableError(ToolError):
    failure_class = FailureClass.UNAVAILABLE


class FailureClassifier(Protocol):
    """Maps a raised exception to a :class:`Failure`."""

    def classify(self, exception: BaseException, *, tool: str, attempt: int) -> Failure:
        ...


# Heuristics applied (in order) to a stringified exception when no typed error is
# present. The first matching pattern wins. Ordering matters: more specific
# patterns come before broader ones.
_PATTERNS: list[tuple[re.Pattern[str], FailureClass]] = [
    (re.compile(r"\b(429|too many requests|rate.?limit|throttl)", re.I), FailureClass.RATE_LIMITED),
    (re.compile(r"\b(401|403|unauthor|forbidden|permission|access denied)", re.I), FailureClass.PERMISSION),
    (re.compile(r"\b(404|not found|no such|does not exist|missing)", re.I), FailureClass.NOT_FOUND),
    (re.compile(r"\b(quota|exhaust|out of memory|disk full|insufficient)", re.I), FailureClass.RESOURCE_EXHAUSTED),
    (re.compile(r"\b(invalid|malformed|bad request|400|validation|schema|expected)", re.I), FailureClass.INVALID_ARGUMENT),
    (re.compile(r"\b(503|502|504|unavailable|connection refused|cannot connect)", re.I), FailureClass.UNAVAILABLE),
    (re.compile(r"\b(timeout|timed out|temporarily|reset by peer|broken pipe)", re.I), FailureClass.TRANSIENT),
]


class HeuristicClassifier:
    """Rule-based classifier.

    Resolution order:

    1. Explicit :class:`ToolError` subclass -> its declared class (confidence 1.0).
    2. Well-known stdlib exception types (e.g. ``TimeoutError``).
    3. Regex heuristics over the message (lower confidence).
    4. Fall back to :attr:`FailureClass.UNKNOWN`.
    """

    _TYPE_MAP: dict[type[BaseException], FailureClass] = {
        TimeoutError: FailureClass.TRANSIENT,
        ConnectionError: FailureClass.UNAVAILABLE,
        ConnectionRefusedError: FailureClass.UNAVAILABLE,
        ConnectionResetError: FailureClass.TRANSIENT,
        PermissionError: FailureClass.PERMISSION,
        FileNotFoundError: FailureClass.NOT_FOUND,
        MemoryError: FailureClass.RESOURCE_EXHAUSTED,
        ValueError: FailureClass.INVALID_ARGUMENT,
        KeyError: FailureClass.INVALID_ARGUMENT,
        TypeError: FailureClass.INVALID_ARGUMENT,
    }

    def classify(self, exception: BaseException, *, tool: str, attempt: int) -> Failure:
        message = str(exception) or exception.__class__.__name__

        if isinstance(exception, ToolError):
            return Failure(
                failure_class=exception.failure_class,
                message=message,
                tool=tool,
                attempt=attempt,
                exception=exception,
                confidence=1.0,
            )

        # Exact-then-subclass type lookup.
        for exc_type, fclass in self._TYPE_MAP.items():
            if type(exception) is exc_type:
                return Failure(fclass, message, tool, attempt, exception, confidence=0.9)

        for pattern, fclass in _PATTERNS:
            if pattern.search(message):
                return Failure(fclass, message, tool, attempt, exception, confidence=0.6)

        for exc_type, fclass in self._TYPE_MAP.items():
            if isinstance(exception, exc_type):
                return Failure(fclass, message, tool, attempt, exception, confidence=0.7)

        return Failure(FailureClass.UNKNOWN, message, tool, attempt, exception, confidence=0.3)
