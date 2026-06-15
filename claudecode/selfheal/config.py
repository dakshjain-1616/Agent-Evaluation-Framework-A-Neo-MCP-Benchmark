"""Configuration objects and retry/backoff policy.

Timing is dependency-injected (``sleep_fn``, ``rng``) so the recovery loop is
fully deterministic under test — no real wall-clock sleeps, no real randomness.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with optional jitter.

    ``delay_for(attempt)`` returns the delay *before* the given (1-based) retry
    attempt. Attempt 1 is the initial call and incurs no delay.
    """

    max_attempts: int = 4
    base_delay: float = 0.1
    backoff_factor: float = 2.0
    max_delay: float = 5.0
    jitter: float = 0.1  # fraction of the computed delay, +/-

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be non-negative")

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """Delay in seconds before ``attempt`` (1-based). 0 for the first attempt."""
        if attempt <= 1:
            return 0.0
        raw = self.base_delay * (self.backoff_factor ** (attempt - 2))
        delay = min(raw, self.max_delay)
        if self.jitter and rng is not None:
            spread = delay * self.jitter
            delay = max(0.0, delay + rng.uniform(-spread, spread))
        return delay


@dataclass
class PipelineConfig:
    """Top-level knobs for a pipeline run."""

    retry_policy: RetryPolicy = RetryPolicy()
    enable_argument_repair: bool = True
    enable_output_verification: bool = True
    # How many times the planner may be re-invoked when a step fails terminally.
    max_replans: int = 1
    # Injected for testability; default to real time.
    sleep_fn: Callable[[float], None] = __import__("time").sleep
    clock: Callable[[], float] = __import__("time").monotonic
    rng: random.Random | None = None
