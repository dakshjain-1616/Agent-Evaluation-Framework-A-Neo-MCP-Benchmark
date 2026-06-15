"""Argument repair.

When a call fails with :class:`FailureClass.INVALID_ARGUMENT`, retrying the exact
same arguments is futile. The repair layer attempts to *fix* the call before the
next attempt — coercing types, filling defaults, dropping unknown keys, and
truncating oversized values according to the tool's declared schema.

``ArgumentRepairer`` is an interface; the default :class:`SchemaRepairer` is
schema-driven, but a custom repairer (rule-based or LLM-backed) can be supplied.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .failures import Failure
from .tools import ArgSpec, Tool


class ArgumentRepairer(Protocol):
    def repair(
        self, tool: Tool, args: Mapping[str, Any], failure: Failure
    ) -> dict[str, Any] | None:
        """Return repaired args, or ``None`` if no repair could be made.

        Returning args equal to the input also signals "no change" and the
        executor will not bother retrying.
        """
        ...


def _coerce(value: Any, target: type) -> Any:
    """Best-effort coercion to ``target``; raises on failure."""
    if isinstance(value, target):
        return value
    if target is bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if target is str:
        return str(value)
    if target in (int, float):
        return target(value)  # may raise ValueError/TypeError
    # Generic last resort.
    return target(value)


class SchemaRepairer:
    """Repairs arguments using each tool's :class:`ArgSpec` schema."""

    def repair(
        self, tool: Tool, args: Mapping[str, Any], failure: Failure
    ) -> dict[str, Any] | None:
        schema: Mapping[str, ArgSpec] = getattr(tool, "schema", {}) or {}
        if not schema:
            return None

        repaired: dict[str, Any] = dict(args)
        changed = False

        # Drop keys the tool doesn't accept.
        for key in list(repaired):
            if key not in schema:
                repaired.pop(key)
                changed = True

        for key, spec in schema.items():
            if key not in repaired:
                if spec.required and spec.default is not None:
                    repaired[key] = spec.default
                    changed = True
                continue

            value = repaired[key]

            # Type coercion.
            if not isinstance(value, spec.type):
                try:
                    coerced = _coerce(value, spec.type)
                except (ValueError, TypeError):
                    # Unrepairable value; fall back to default if we have one.
                    if spec.default is not None:
                        repaired[key] = spec.default
                        changed = True
                    continue
                if coerced != value:
                    repaired[key] = coerced
                    value = coerced
                    changed = True

            # Length capping for sized values.
            if spec.max_len is not None:
                try:
                    if len(value) > spec.max_len:
                        repaired[key] = value[: spec.max_len]
                        changed = True
                except TypeError:
                    pass

        if not changed or repaired == dict(args):
            return None
        return repaired
