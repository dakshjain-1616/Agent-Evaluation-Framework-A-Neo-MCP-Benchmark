from __future__ import annotations

from selfheal import (
    ArgSpec,
    CallablePlanner,
    FunctionTool,
    PermissionDeniedError,
    PipelineStatus,
    Step,
    StaticPlanner,
    TransientError,
    build_pipeline,
)


def test_full_pipeline_success_with_recovery(fast_config, clock):
    fast_config.clock = clock.now
    planner = StaticPlanner([
        Step("fetch", {"url": "u"}, name="fetch"),
        Step("score", {"value": "10"}, name="score"),
    ])
    pipeline, registry, obs = build_pipeline(planner, config=fast_config)

    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TransientError("blip")
        return {"url": url}

    registry.register(FunctionTool("fetch", fetch, schema={"url": ArgSpec(str)}))
    registry.register(FunctionTool("score", lambda value: value + 1,
                                   schema={"value": ArgSpec(int)}))

    result = pipeline.run("do the thing")
    assert result.status is PipelineStatus.SUCCESS
    assert len(result.steps) == 2
    assert result.steps[1].value == 11        # "10" repaired to 10, then +1
    assert result.value == 11


def test_pipeline_passes_results_into_context(fast_config):
    seen = {}

    def planner_fn(ctx):
        seen["results"] = dict(ctx.results)
        return [Step("emit", {}, name="emit")]

    planner = CallablePlanner(planner_fn)
    pipeline, registry, obs = build_pipeline(planner, config=fast_config)
    registry.register(FunctionTool("emit", lambda: "ok"))

    pipeline.run("g", context={"seed": 1})
    assert seen["results"] == {"seed": 1}


def test_replan_routes_around_terminal_failure(fast_config):
    """First plan hits a permission wall; replan swaps in a working tool."""
    attempts = {"plans": 0}

    def planner_fn(ctx):
        attempts["plans"] += 1
        if ctx.last_failure is None:
            return [Step("primary", {}, name="primary")]
        # Replanning with failure context -> use the fallback path.
        assert ctx.last_failure.failure_class.terminal
        return [Step("fallback", {}, name="fallback")]

    planner = CallablePlanner(planner_fn)
    pipeline, registry, obs = build_pipeline(planner, config=fast_config)

    def primary():
        raise PermissionDeniedError("no access")

    registry.register(FunctionTool("primary", primary))
    registry.register(FunctionTool("fallback", lambda: "via fallback"))

    result = pipeline.run("achieve goal")
    assert result.status is PipelineStatus.SUCCESS
    assert result.replans == 1
    assert result.value == "via fallback"
    assert attempts["plans"] == 2


def test_pipeline_fails_when_replan_budget_exhausted(fast_config):
    fast_config.max_replans = 0
    planner = StaticPlanner([Step("primary", {}, name="primary")])
    pipeline, registry, obs = build_pipeline(planner, config=fast_config)
    registry.register(FunctionTool("primary", lambda: (_ for _ in ()).throw(
        PermissionDeniedError("no access"))))

    result = pipeline.run("goal")
    assert result.status is PipelineStatus.FAILED
    assert result.replans == 0
