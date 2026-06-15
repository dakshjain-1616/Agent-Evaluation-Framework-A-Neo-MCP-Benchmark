"""Failure classifier — pattern-matches errors to failure categories."""

from __future__ import annotations

import re
from typing import Optional

from neo_mcp.core.interfaces import FailureClassifier
from neo_mcp.core.models import (
    FailureCategory,
    FailureClassification,
    RecoveryAction,
)


class RuleBasedFailureClassifier(FailureClassifier):
    """Classifies failures by pattern-matching error messages and exception types.

    Rules are evaluated in priority order. The first matching rule determines the
    classification. Rules cover common failure modes:

    - HTTP 429 / rate limit → TRANSIENT (retry)
    - timeout / ConnectionError → TRANSIENT (retry)
    - 401 / 403 / auth errors → PERMANENT_AUTH (fail/escalate)
    - KeyError / TypeError / ValidationError / schema violations → PERMANENT_BAD_ARGS (repair & retry)
    - 500 / 502 / 503 → PERMANENT_DOWNSTREAM (escalate)
    - Everything else → UNKNOWN (fail)
    """

    # Rule format: (match_fn, category, action, is_transient, requires_repair)
    def __init__(self) -> None:
        self._rules = self._build_rules()

    def _build_rules(self):
        """Build the ordered list of classification rules."""
        return [
            # --- TRANSIENT: rate limits ---
            self._rule(
                lambda msg, exc: (
                    "429" in msg
                    or re.search(r"rate.?limit", msg, re.IGNORECASE) is not None
                    or "too many requests" in msg.lower()
                ),
                FailureCategory.TRANSIENT,
                RecoveryAction.RETRY,
                is_transient=True,
                details="Rate limit detected — will retry with backoff",
            ),
            # --- TRANSIENT: timeouts ---
            self._rule(
                lambda msg, exc: (
                    "timeout" in msg.lower()
                    or "timed out" in msg.lower()
                    or "time_out" in msg.lower()
                    or (exc is not None and "TimeoutError" in exc)
                ),
                FailureCategory.TRANSIENT,
                RecoveryAction.RETRY,
                is_transient=True,
                details="Timeout detected — will retry with backoff",
            ),
            # --- TRANSIENT: connection / network ---
            self._rule(
                lambda msg, exc: (
                    exc is not None
                    and (
                        "ConnectionError" in exc
                        or "ConnectionResetError" in exc
                        or "ConnectionRefusedError" in exc
                    )
                )
                or "connection refused" in msg.lower()
                or "connection reset" in msg.lower(),
                FailureCategory.TRANSIENT,
                RecoveryAction.RETRY,
                is_transient=True,
                details="Network error detected — will retry",
            ),
            # --- PERMANENT_AUTH: auth errors ---
            self._rule(
                lambda msg, exc: (
                    "401" in msg
                    or "403" in msg
                    or "unauthorized" in msg.lower()
                    or "forbidden" in msg.lower()
                    or "invalid api key" in msg.lower()
                    or "authentication failed" in msg.lower()
                ),
                FailureCategory.PERMANENT_AUTH,
                RecoveryAction.FAIL,
                is_transient=False,
                details="Authentication failure — cannot retry with same credentials",
            ),
            # --- PERMANENT_BAD_ARGS: type/key/validation errors ---
            self._rule(
                lambda msg, exc: (
                    exc is not None
                    and (
                        "KeyError" in exc
                        or "TypeError" in exc
                        or "ValueError" in exc
                    )
                )
                or "validationerror" in msg.lower().replace(" ", "")
                or "validation error" in msg.lower()
                or "schema violation" in msg.lower()
                or "invalid argument" in msg.lower()
                or "missing required" in msg.lower(),
                FailureCategory.PERMANENT_BAD_ARGS,
                RecoveryAction.REPAIR_AND_RETRY,
                is_transient=False,
                requires_repair=True,
                details="Bad arguments — will attempt repair and retry",
            ),
            # --- TRANSIENT: output verification failures ---
            self._rule(
                lambda msg, exc: (
                    "output verification failed" in msg.lower()
                    or "outputverificationerror" in msg.lower().replace(" ", "")
                    or "output did not match" in msg.lower()
                ),
                FailureCategory.TRANSIENT,
                RecoveryAction.RETRY,
                is_transient=True,
                details="Output verification failure — will retry",
            ),
            # --- PERMANENT_DOWNSTREAM: 5xx / service errors ---
            self._rule(
                lambda msg, exc: (
                    "500" in msg
                    or "502" in msg
                    or "503" in msg
                    or "service unavailable" in msg.lower()
                    or "internal server error" in msg.lower()
                ),
                FailureCategory.PERMANENT_DOWNSTREAM,
                RecoveryAction.ESCALATE,
                is_transient=False,
                details="Downstream service error — escalating",
            ),
        ]

    def _rule(self, match_fn, category, action, **kwargs):
        return (match_fn, category, action, kwargs)

    def classify(
        self,
        error_message: str,
        exception_type: Optional[str] = None,
    ) -> FailureClassification:
        """Classify the failure by matching against rules in priority order."""
        if not error_message:
            error_message = ""
        msg_lower = error_message.lower()

        for match_fn, category, action, extra in self._rules:
            if match_fn(msg_lower, exception_type):
                return FailureClassification(
                    category=category,
                    action=action,
                    details=extra.get("details"),
                    is_transient=extra.get("is_transient", False),
                    requires_repair=extra.get("requires_repair", False),
                )

        # Default: UNKNOWN
        return FailureClassification(
            category=FailureCategory.UNKNOWN,
            action=RecoveryAction.FAIL,
            details="No matching rule — classified as unknown",
            is_transient=False,
            requires_repair=False,
        )