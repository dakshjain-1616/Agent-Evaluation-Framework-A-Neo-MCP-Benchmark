"""Observability layer: structured logging, metrics, and tracing."""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from neo_mcp.core.interfaces import Instrumentation


class ConsoleInstrumentation(Instrumentation):
    """Instrumentation implementation that logs structured JSON to stdout
    and keeps in-memory buffers for metrics and traces.

    Thread-safe for single-threaded async use.
    """

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self._metrics: Counter = Counter()
        self._traces: List[Dict[str, Any]] = []
        self._log_buffer: List[Dict[str, Any]] = []

    def log(
        self,
        level: str,
        message: str,
        **context: Any,
    ) -> None:
        """Emit a structured JSON log entry."""
        entry: Dict[str, Any] = {
            "level": level.upper(),
            "message": message,
            "timestamp": time.time(),
        }
        if context:
            entry["context"] = context

        self._log_buffer.append(entry)

        if self.verbose:
            print(json.dumps(entry))

    def increment(
        self,
        metric_name: str,
        value: int = 1,
        **tags: Any,
    ) -> None:
        """Increment a counter metric."""
        key = metric_name
        if tags:
            tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{metric_name}[{tag_str}]"
        self._metrics[key] += value

    def record_trace(
        self,
        step_id: str,
        event: str,
        duration_ms: float,
        **attributes: Any,
    ) -> None:
        """Record a trace event for a step."""
        trace_entry: Dict[str, Any] = {
            "step_id": step_id,
            "event": event,
            "duration_ms": round(duration_ms, 2),
            "timestamp": time.time(),
        }
        if attributes:
            trace_entry["attributes"] = attributes

        self._traces.append(trace_entry)

        if self.verbose:
            print(
                json.dumps(
                    {
                        "type": "trace",
                        "step_id": step_id,
                        "event": event,
                        "duration_ms": round(duration_ms, 2),
                    }
                )
            )

    def get_metrics_snapshot(self) -> Dict[str, int]:
        """Return a snapshot of all accumulated metrics counters."""
        return dict(self._metrics)

    def get_traces(self) -> List[Dict[str, Any]]:
        """Return all recorded traces."""
        return list(self._traces)

    def get_logs(self) -> List[Dict[str, Any]]:
        """Return all recorded log entries."""
        return list(self._log_buffer)

    def clear(self) -> None:
        """Clear all in-memory buffers (useful for test isolation)."""
        self._metrics.clear()
        self._traces.clear()
        self._log_buffer.clear()