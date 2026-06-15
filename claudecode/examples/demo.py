"""End-to-end demo of the self-healing pipeline.

Runs a plan whose tools fail in different ways — a transient blip, a malformed
argument, a rate limit — and shows the pipeline classify, repair, retry, verify,
recover, and report. Run with::

    python -m examples.demo        # from the project root
"""

from __future__ import annotations

import json

from selfheal import (
    ArgSpec,
    FunctionTool,
    InMemorySink,
    PipelineConfig,
    RateLimitError,
    RetryPolicy,
    Step,
    StaticPlanner,
    TransientError,
    build_pipeline,
)


def make_flaky_fetch():
    """Fails transiently twice, then succeeds — exercises retry."""
    state = {"calls": 0}

    def fetch(url: str):
        state["calls"] += 1
        if state["calls"] < 3:
            raise TransientError(f"temporary network glitch talking to {url}")
        return {"url": url, "status": 200, "body": "payload"}

    return fetch


def make_rate_limited_summarize():
    """Rate-limited once, then succeeds — exercises backoff."""
    state = {"calls": 0}

    def summarize(text: str):
        state["calls"] += 1
        if state["calls"] < 2:
            raise RateLimitError("429 too many requests")
        return f"summary({len(text)} chars)"

    return summarize


def coerce_score(value: int):
    """Strictly expects an int; the plan passes a string to trigger repair."""
    if not isinstance(value, int):
        raise ValueError(f"expected int, got {type(value).__name__}")
    return {"score": value * 2}


def main() -> int:
    # Deterministic, fast config: no real sleeping, fixed jitter source.
    import random

    config = PipelineConfig(
        retry_policy=RetryPolicy(max_attempts=5, base_delay=0.01, max_delay=0.05),
        sleep_fn=lambda _s: None,          # don't actually sleep in the demo
        rng=random.Random(7),
    )

    planner = StaticPlanner([
        Step("fetch", {"url": "https://example.com/data"}, name="fetch"),
        Step("score", {"value": "21"}, name="score"),        # str -> int repair
        Step("summarize", {"text": "the quick brown fox"}, name="summarize"),
    ])

    sink = InMemorySink()
    pipeline, registry, obs = build_pipeline(planner, config=config, sink=sink)

    registry.register(FunctionTool("fetch", make_flaky_fetch(),
                                   schema={"url": ArgSpec(str)}))
    registry.register(FunctionTool("score", coerce_score,
                                   schema={"value": ArgSpec(int)}))
    registry.register(FunctionTool("summarize", make_rate_limited_summarize(),
                                   schema={"text": ArgSpec(str, max_len=10_000)}))

    result = pipeline.run("fetch, score, and summarize the document")

    print("=== Pipeline result ===")
    print(f"status : {result.status.value}")
    for step in result.steps:
        print(f"  - {step.tool:<10} {step.status.value:<10} "
              f"attempts={step.attempts} value={step.value!r}")

    print("\n=== Metrics ===")
    print(json.dumps(obs.metrics.snapshot(), indent=2))

    print("\n=== Incidents ===")
    for incident in obs.incidents.incidents:
        print(json.dumps(incident.report(), indent=2))

    return 0 if result.status.value == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
