from __future__ import annotations

import json

from selfheal import (
    EventKind,
    FunctionTool,
    InMemorySink,
    Observability,
    ResilientExecutor,
    ToolRegistry,
    TransientError,
)


def _run_flaky(fast_config, clock):
    sink = InMemorySink()
    obs = Observability(sink=sink, clock=clock.now)
    registry = ToolRegistry()
    ex = ResilientExecutor(registry, obs, config=fast_config)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TransientError("blip")
        return "ok"

    registry.register(FunctionTool("flaky", flaky))
    ex.execute("flaky", {})
    return sink, obs


def test_events_emitted_in_expected_order(fast_config, clock):
    sink, obs = _run_flaky(fast_config, clock)
    kinds = [e.kind for e in sink.events]
    assert kinds[0] is EventKind.ATTEMPT_START
    assert EventKind.ATTEMPT_FAILURE in kinds
    assert EventKind.CLASSIFIED in kinds
    assert kinds[-1] is EventKind.RECOVERED


def test_events_are_json_serialisable(fast_config, clock):
    sink, _ = _run_flaky(fast_config, clock)
    for event in sink.events:
        payload = json.dumps(event.to_dict(), default=str)
        assert json.loads(payload)["kind"] == event.kind.value


def test_metrics_snapshot_shape(fast_config, clock):
    _, obs = _run_flaky(fast_config, clock)
    snap = obs.metrics.snapshot()
    assert snap["successes"] == 1
    assert snap["recoveries"] == 1
    assert snap["failures"] == 1
    assert snap["failures_by_class"] == {"transient": 1}
    assert 0.0 <= snap["success_rate"] <= 1.0


def test_incident_report_captures_timeline(fast_config, clock):
    _, obs = _run_flaky(fast_config, clock)
    assert len(obs.incidents.incidents) == 1
    report = obs.incidents.incidents[0].report()
    assert report["tool"] == "flaky"
    assert report["resolved"] is True
    assert report["attempts"] == 2
    assert report["final_failure"] is None
