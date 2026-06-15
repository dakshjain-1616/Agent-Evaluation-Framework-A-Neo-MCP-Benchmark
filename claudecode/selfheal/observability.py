"""Built-in observability: structured events, metrics, and incident records.

Observability is a first-class part of the architecture, not plumbing bolted on
afterwards. Every meaningful moment in the recovery loop emits a structured
:class:`Event`; metrics aggregate those events; and an :class:`IncidentRecorder`
captures the full timeline whenever recovery is attempted, so each incident can
be replayed and audited after the fact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from .failures import Failure, FailureClass


class EventKind(str, Enum):
    ATTEMPT_START = "attempt_start"
    ATTEMPT_SUCCESS = "attempt_success"
    ATTEMPT_FAILURE = "attempt_failure"
    CLASSIFIED = "classified"
    REPAIR_APPLIED = "repair_applied"
    REPAIR_SKIPPED = "repair_skipped"
    BACKOFF = "backoff"
    VERIFICATION_FAILED = "verification_failed"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    STEP_START = "step_start"
    STEP_DONE = "step_done"
    PLAN_CREATED = "plan_created"
    REPLAN = "replan"


@dataclass
class Event:
    """A single structured observability record."""

    kind: EventKind
    ts: float
    tool: str | None = None
    attempt: int | None = None
    failure_class: FailureClass | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["failure_class"] = self.failure_class.value if self.failure_class else None
        return d


class EventSink(Protocol):
    def emit(self, event: Event) -> None:
        ...


class InMemorySink:
    """Collects events in a list — useful for tests and post-run inspection."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind == kind]


class LoggingSink:
    """Emits events as single-line JSON via the stdlib logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("selfheal")

    def emit(self, event: Event) -> None:
        self.logger.info(json.dumps(event.to_dict(), default=str, sort_keys=True))


class MultiSink:
    """Fans an event out to several sinks."""

    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self.sinks:
            sink.emit(event)


@dataclass
class Metrics:
    """Running counters and timings for a pipeline run."""

    attempts: int = 0
    successes: int = 0
    failures: int = 0
    recoveries: int = 0
    escalations: int = 0
    repairs: int = 0
    backoff_seconds: float = 0.0
    failures_by_class: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)

    def record_failure(self, fclass: FailureClass) -> None:
        self.failures += 1
        key = fclass.value
        self.failures_by_class[key] = self.failures_by_class.get(key, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        n = len(self.latencies)
        avg = sum(self.latencies) / n if n else 0.0
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "recoveries": self.recoveries,
            "escalations": self.escalations,
            "repairs": self.repairs,
            "backoff_seconds": round(self.backoff_seconds, 6),
            "failures_by_class": dict(self.failures_by_class),
            "avg_attempt_latency": round(avg, 6),
            "success_rate": round(self.successes / self.attempts, 4) if self.attempts else 0.0,
        }


@dataclass
class Incident:
    """The full recovery timeline for a single step that experienced failure."""

    tool: str
    timeline: list[Event] = field(default_factory=list)
    resolved: bool = False
    resolution: str = ""
    final_failure: Failure | None = None

    def report(self) -> dict[str, Any]:
        # The incident opens lazily on the first failure, so the first
        # ATTEMPT_START may predate it. Derive the attempt count from the highest
        # attempt number any recorded event carries instead of counting starts.
        attempts = max((e.attempt for e in self.timeline if e.attempt), default=0)
        return {
            "tool": self.tool,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "attempts": attempts,
            "recovery_path": [e.kind.value for e in self.timeline],
            "final_failure": str(self.final_failure) if self.final_failure else None,
        }


class IncidentRecorder:
    """Opens an incident on first failure of a step and records its resolution."""

    def __init__(self) -> None:
        self.incidents: list[Incident] = []
        self._open: Incident | None = None

    def ensure_open(self, tool: str) -> Incident:
        if self._open is None:
            self._open = Incident(tool=tool)
            self.incidents.append(self._open)
        return self._open

    def note(self, event: Event) -> None:
        if self._open is not None:
            self._open.timeline.append(event)

    def resolve(self, resolution: str) -> None:
        if self._open is not None:
            self._open.resolved = True
            self._open.resolution = resolution
            self._open = None

    def fail(self, failure: Failure, resolution: str) -> None:
        if self._open is not None:
            self._open.resolved = False
            self._open.resolution = resolution
            self._open.final_failure = failure
            self._open = None


class Observability:
    """Facade bundling the event sink, metrics, and incident recorder.

    A single ``clock`` is injected so event timestamps and latencies are
    deterministic under test.
    """

    def __init__(self, sink: EventSink | None = None, clock: Callable[[], float] | None = None) -> None:
        self.sink = sink or InMemorySink()
        self.metrics = Metrics()
        self.incidents = IncidentRecorder()
        self._clock = clock or __import__("time").monotonic

    def emit(self, kind: EventKind, **kwargs: Any) -> Event:
        event = Event(kind=kind, ts=self._clock(), **kwargs)
        self.sink.emit(event)
        self.incidents.note(event)
        return event
