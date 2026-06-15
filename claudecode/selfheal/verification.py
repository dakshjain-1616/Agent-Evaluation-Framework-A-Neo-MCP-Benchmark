"""Output verification.

A call returning without raising does not mean it *succeeded*. A tool can return
an empty result, a malformed payload, or something that violates a downstream
contract. Verifiers turn "no exception" into "verified good output", and a failed
verification is treated as a :class:`FailureClass.BAD_OUTPUT` failure — which is
repairable and retryable, just like a raised error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .tools import Tool


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str = ""

    @classmethod
    def good(cls) -> "VerificationResult":
        return cls(True)

    @classmethod
    def bad(cls, reason: str) -> "VerificationResult":
        return cls(False, reason)


class OutputVerifier(Protocol):
    def verify(self, tool: Tool, args: dict[str, Any], result: Any) -> VerificationResult:
        ...


class AlwaysValid:
    """Default no-op verifier."""

    def verify(self, tool: Tool, args: dict[str, Any], result: Any) -> VerificationResult:
        return VerificationResult.good()


class NonEmptyVerifier:
    """Rejects ``None`` and empty containers/strings."""

    def verify(self, tool: Tool, args: dict[str, Any], result: Any) -> VerificationResult:
        if result is None:
            return VerificationResult.bad("result is None")
        if isinstance(result, (str, bytes, list, tuple, dict, set)) and len(result) == 0:
            return VerificationResult.bad("result is empty")
        return VerificationResult.good()


class PredicateVerifier:
    """Wraps a user predicate ``(result) -> bool``."""

    def __init__(self, predicate: Callable[[Any], bool], reason: str = "predicate failed") -> None:
        self._predicate = predicate
        self._reason = reason

    def verify(self, tool: Tool, args: dict[str, Any], result: Any) -> VerificationResult:
        return VerificationResult.good() if self._predicate(result) else VerificationResult.bad(self._reason)
