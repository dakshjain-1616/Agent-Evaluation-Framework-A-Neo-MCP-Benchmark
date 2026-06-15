"""Shared test fixtures: deterministic config and a fake clock."""

from __future__ import annotations

import random

import pytest

from selfheal import PipelineConfig, RetryPolicy


class FakeClock:
    """Monotonic clock that advances only when ``sleep`` is called."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fast_config(clock: FakeClock) -> PipelineConfig:
    """No real sleeping, deterministic jitter, generous attempt budget."""
    return PipelineConfig(
        retry_policy=RetryPolicy(max_attempts=5, base_delay=0.1, max_delay=1.0, jitter=0.0),
        sleep_fn=clock.sleep,
        clock=clock.now,
        rng=random.Random(0),
    )
