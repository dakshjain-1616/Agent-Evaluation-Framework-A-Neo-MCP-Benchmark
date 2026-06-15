# selfheal — a self-healing AI pipeline

A production-grade framework for running AI/agent tool-calls that **detect
failures, diagnose their root cause, recover autonomously, verify the outcome,
and stay observable** the whole way through.

It is built around one idea: *self-healing is not "retry until it works."* It is

> understand **why** something broke → classify the failure → decide whether it
> is transient → repair the call if possible → retry → verify the output →
> record the recovery path → escalate only if required.

That loop is implemented once, in [`selfheal/executor.py`](selfheal/executor.py),
and everything else plugs into it through interfaces.

## Architecture

```
                         SelfHealingPipeline  (pipeline.py)
                          plan → run steps → replan-on-terminal
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 ▼                     ▼                      ▼
        PlanningEngine          ResilientExecutor         Observability
         (planning.py)            (executor.py)          (observability.py)
       pluggable: static,      the recovery loop:        structured events,
       callable, LLM-backed    classify→repair→retry     metrics, incidents
                                 →verify→record→escalate
                 ┌──────────────┬──────────────┬───────────────┐
                 ▼              ▼              ▼               ▼
          FailureClassifier  ArgumentRepairer  OutputVerifier  RetryPolicy
           (failures.py)      (repair.py)      (verification.py) (config.py)
```

Every collaborator is an interface with a sensible default, so each concern can
be swapped independently:

| Concern              | Interface           | Default implementation        |
| -------------------- | ------------------- | ----------------------------- |
| Failure diagnosis    | `FailureClassifier` | `HeuristicClassifier`         |
| Argument repair      | `ArgumentRepairer`  | `SchemaRepairer`              |
| Output verification  | `OutputVerifier`    | `AlwaysValid` / `NonEmpty` …  |
| Planning             | `PlanningEngine`    | `StaticPlanner` / `Callable…` |
| Retry/backoff        | `RetryPolicy`       | exponential + jitter          |
| Observability sink   | `EventSink`         | `InMemorySink` / `LoggingSink`|

## The recovery loop

For each tool call the executor:

1. **Runs** the tool.
2. On error, **classifies** it into a [`FailureClass`](selfheal/failures.py)
   (transient, rate-limited, invalid-argument, permission, not-found, …).
3. **Chooses an action from the class**, not from a blind counter:
   - *terminal* (permission / not-found / logic bug) → escalate immediately, no
     pointless retries;
   - *repairable* (bad argument / bad output) → repair the arguments via the
     schema, then retry;
   - *transient / backoff* → retry, waiting only when the class calls for it
     (rate-limit and resource-exhaustion back off; a network blip retries at
     once).
4. **Verifies** successful output — a call that returns `""` or `None` is a
   `BAD_OUTPUT` failure, handled like any other.
5. **Records** the entire path as an `Incident` and updates `Metrics`.
6. **Escalates** with the final classified failure when recovery is impossible
   or the retry budget is spent.

On top of call-level recovery, the pipeline does **strategy-level** recovery: if
a step escalates, it can ask the planner to *replan* with the failure in context
(e.g. route around a permission wall to a fallback tool), bounded by
`max_replans`.

## Quick start

```python
from selfheal import (build_pipeline, FunctionTool, ArgSpec, Step,
                      StaticPlanner, TransientError)

planner = StaticPlanner([Step("fetch", {"url": "https://example.com"})])
pipeline, registry, obs = build_pipeline(planner)

calls = {"n": 0}
def fetch(url):
    calls["n"] += 1
    if calls["n"] < 2:
        raise TransientError("network blip")   # classified + retried
    return {"url": url, "status": 200}

registry.register(FunctionTool("fetch", fetch, schema={"url": ArgSpec(str)}))

result = pipeline.run("fetch the page")
print(result.status.value)          # "success"
print(obs.metrics.snapshot())       # attempts, recoveries, failures_by_class …
for inc in obs.incidents.incidents:
    print(inc.report())             # full recovery timeline per incident
```

## Run it

```bash
python -m examples.demo     # full demo: transient retry, arg repair, backoff
python -m pytest            # 34 tests
```

The demo wires up three deliberately flaky tools and prints the pipeline result,
the metrics snapshot, and the per-incident recovery timelines.

## Testability

Timing is dependency-injected (`sleep_fn`, `clock`, `rng` on `PipelineConfig`),
so the recovery loop — including backoff — runs deterministically and instantly
under test, with no real sleeps. The test suite covers classification, repair,
verification, every executor recovery branch, pipeline replanning, and the
observability/metrics/incident surfaces.

## Design notes

- **Failure class drives behavior.** Retry counts are a backstop, not the
  policy. A permission error escalates on attempt 1; a malformed argument is
  repaired before the next attempt; a rate limit backs off.
- **`INVALID_ARGUMENT` vs `BAD_OUTPUT`.** A malformed argument is deterministic —
  retrying it unchanged is pointless, so without a repair it escalates. A bad
  *output* may differ on a re-run (nondeterministic models), so it stays
  retryable even without a repair.
- **Observability is structural.** Events, metrics, and incident records are
  emitted from inside the loop, not added afterward, so an operator can always
  answer "what broke, why, and how did it recover?"
