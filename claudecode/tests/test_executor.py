from __future__ import annotations

import pytest

from selfheal import (
    ArgSpec,
    EventKind,
    FailureClass,
    FunctionTool,
    Observability,
    PermissionDeniedError,
    RateLimitError,
    ResilientExecutor,
    StepStatus,
    ToolRegistry,
    TransientError,
)
from selfheal.verification import NonEmptyVerifier


def _make(fast_config, clock, *, verifier=None):
    registry = ToolRegistry()
    obs = Observability(clock=clock.now)
    ex = ResilientExecutor(registry, obs, config=fast_config, verifier=verifier)
    return registry, obs, ex


def test_success_first_try(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)
    registry.register(FunctionTool("ok", lambda: "value"))
    res = ex.execute("ok", {})
    assert res.status is StepStatus.SUCCESS
    assert res.value == "value"
    assert res.attempts == 1
    assert obs.metrics.successes == 1
    assert obs.metrics.recoveries == 0
    assert not obs.incidents.incidents  # no incident opened on clean success


def test_recovers_after_transient_failures(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("blip")
        return "done"

    registry.register(FunctionTool("flaky", flaky))
    res = ex.execute("flaky", {})
    assert res.status is StepStatus.RECOVERED
    assert res.attempts == 3
    assert obs.metrics.recoveries == 1
    # transient failures retry immediately -> no backoff sleeps
    assert clock.sleeps == []
    inc = obs.incidents.incidents[0].report()
    assert inc["resolved"] is True
    assert EventKind.RECOVERED.value in inc["recovery_path"]


def test_backoff_applied_for_rate_limit(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)
    calls = {"n": 0}

    def limited():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    registry.register(FunctionTool("limited", limited))
    res = ex.execute("limited", {})
    assert res.status is StepStatus.RECOVERED
    # two failures -> two backoff sleeps before attempts 2 and 3
    assert len(clock.sleeps) == 2
    assert obs.metrics.backoff_seconds > 0


def test_argument_repair_then_success(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)

    def needs_int(value):
        if not isinstance(value, int):
            raise ValueError("expected int")
        return value * 2

    registry.register(FunctionTool("score", needs_int, schema={"value": ArgSpec(int)}))
    res = ex.execute("score", {"value": "21"})
    assert res.status is StepStatus.RECOVERED
    assert res.value == 42
    assert res.final_args == {"value": 21}
    assert obs.metrics.repairs == 1


def test_terminal_failure_escalates_immediately(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)

    def denied():
        raise PermissionDeniedError("403")

    registry.register(FunctionTool("denied", denied))
    res = ex.execute("denied", {})
    assert res.status is StepStatus.ESCALATED
    assert res.attempts == 1  # no pointless retries
    assert res.failure.failure_class is FailureClass.PERMISSION
    assert obs.metrics.escalations == 1


def test_retries_exhausted_escalates(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)

    def always_transient():
        raise TransientError("never recovers")

    registry.register(FunctionTool("t", always_transient))
    res = ex.execute("t", {})
    assert res.status is StepStatus.ESCALATED
    assert res.attempts == fast_config.retry_policy.max_attempts


def test_bad_output_triggers_recovery(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock, verifier=NonEmptyVerifier())
    calls = {"n": 0}

    def sometimes_empty():
        calls["n"] += 1
        return "" if calls["n"] < 2 else "real"

    registry.register(FunctionTool("e", sometimes_empty))
    res = ex.execute("e", {})
    assert res.status is StepStatus.RECOVERED
    assert res.value == "real"
    assert obs.metrics.failures_by_class.get(FailureClass.BAD_OUTPUT.value) == 1


def test_unrepairable_bad_argument_escalates(fast_config, clock):
    registry, obs, ex = _make(fast_config, clock)

    # No schema -> repairer can't help -> non-transient invalid arg escalates.
    def bad(value):
        raise ValueError("invalid argument always")

    registry.register(FunctionTool("bad", bad))
    res = ex.execute("bad", {"value": 1})
    assert res.status is StepStatus.ESCALATED
    assert res.attempts == 1
