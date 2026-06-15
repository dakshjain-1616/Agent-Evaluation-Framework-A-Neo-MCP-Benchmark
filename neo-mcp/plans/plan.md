# Neo-MCP Evaluation Layer

## Goal
Build a new `neo_mcp/evaluation/` package that sits ON TOP of the existing self-healing agent platform, consuming its public interfaces (`SelfHealingAgent`, `AgentResult`, `Instrumentation`, `FailureClassifier`) to run agent evaluations over datasets, score results, detect regressions, and support human review hooks — without modifying any core files.

## Research Summary
- Explored full codebase: core models (`Step`, `Plan`, `StepResult`, `AgentResult`, `IncidentRecord`, `Verdict`), interfaces (`Planner`, `Executor`, `FailureClassifier`, `Instrumentation`, etc.), `SelfHealingAgent` orchestrator, `ConsoleInstrumentation`, `RuleBasedFailureClassifier`, `FixedPlanner`, demo tools/runner
- Existing test suite: 137 tests in `neo_mcp/tests/` using `pytest-asyncio` (auto mode)
- Existing package structure: flat `neo_mcp/` with `__init__.py` (empty), subpackages for `core/`, `recovery/`, `planners/`, `executor/`, `agent/`, `observability/`, `demos/`, `tests/`
- No modifications will be made to any existing files — this is purely additive

## Approach
Build 6 clean modules in `neo_mcp/evaluation/` behind ABC interfaces with concrete reference implementations. Each module has a clear public API consumed by the others. Demonstrate end-to-end with `eval_demo.py`. Test with fakes/mocks (no real LLM calls). All components reuse existing platform types via import — never fork them.

## Subtasks
1. **Create package structure**: `neo_mcp/evaluation/__init__.py` + directory scaffolding
2. **Datasets** (`evaluation/datasets.py`):
   - `EvaluationCase` dataclass (id, input/goal, expected_output, metadata)
   - `EvaluationDataset` ABC with `load()`, `sample(n, seed)`, `split(...)`, `version` property
   - `InMemoryDataset` — list of cases, content-hash versioning
   - `JsonlDataset` — load cases from JSONL file
3. **Scoring** (`evaluation/scoring.py`):
   - `MetricResult` dataclass (name, value, passed, detail)
   - `EvaluationMetric` ABC with `score(case, agent_result) -> MetricResult`
   - `ExactMatchMetric` — compares expected_output to agent output
   - `SuccessRateMetric` — did agent succeed per `AgentResult.success`
   - `LatencyMetric` — total execution time
   - `RecoveryCountMetric` — number of incidents/recoveries
   - `ScoreAggregator` — rolls per-case metrics into run-level summary (mean, pass-rate)
4. **Runner** (`evaluation/runner.py`):
   - `EvaluationReport` dataclass (per_case_results, aggregated, config, dataset_version)
   - `EvaluationRunner` — takes agent factory + dataset + metrics, runs each case, collects results
   - Bounded concurrency via asyncio semaphore
   - Graceful failure handling (never crashes)
   - Deterministic, seedable
5. **Regression detection** (`evaluation/regression.py`):
   - `BaselineStore` ABC + `JsonBaselineStore`
   - `RegressionDetector` — threshold/delta comparison of reports
   - `RegressionVerdict` — per-metric: baseline, current, delta, regressed
6. **Human review hook** (`evaluation/review.py`):
   - `ReviewQueue` ABC + `InMemoryReviewQueue`
   - `enqueue(case, result, reason)`, `pending()`, `resolve(id, verdict)`
7. **Eval instrumentation** (`evaluation/eval_instrumentation.py`):
   - `EvalInstrumentation` — thin wrapper that composes with existing `Instrumentation`
   - `EVAL_FAILURE_PATTERNS` — extension to `RuleBasedFailureClassifier` via composition (not subclassing), registering eval-specific failure categories
8. **E2E demo** (`evaluation/eval_demo.py`):
   - Small in-memory dataset → `SelfHealingAgent` (with `FixedPlanner` + demo tools) → batch run → scoring → aggregation → baseline → regression detection → review queue
   - Run twice: first establishes baseline, second (with injected degradation) shows regression caught
9. **Tests** (`neo_mcp/tests/evaluation/`):
   - `test_datasets.py` — test load/sample/split/versioning
   - `test_scoring.py` — test each metric + aggregator
   - `test_runner.py` — test runner with fake agent
   - `test_regression.py` — test baseline store + regression detection
   - `test_review.py` — test review queue
   - `test_eval_instrumentation.py` — test composition with instrumentation
10. **Docs** (`docs/EVALUATION.md`): architecture, how it consumes the core, how to add metrics/datasets/detectors
11. **Final verification**: run `pytest neo_mcp/tests/ -v` (all existing 137 + new evaluation tests pass), run `python -m neo_mcp.evaluation.eval_demo`, confirm core files untouched

## Interface Design Principles
- Every component behind an ABC that can be implemented independently
- All types defined cleanly — metrics receive `EvaluationCase` + `AgentResult` directly
- No external dependencies beyond what neo-mcp already uses (standard lib + asyncio + json)
- Evaluation layer imports from existing core — never the reverse

## Deliverables
| File Path | Description |
|-----------|-------------|
| `neo_mcp/evaluation/__init__.py` | Package marker |
| `neo_mcp/evaluation/datasets.py` | EvaluationCase, EvaluationDataset, InMemoryDataset, JsonlDataset |
| `neo_mcp/evaluation/scoring.py` | MetricResult, EvaluationMetric, ExactMatchMetric, SuccessRateMetric, LatencyMetric, RecoveryCountMetric, ScoreAggregator |
| `neo_mcp/evaluation/runner.py` | EvaluationReport, EvaluationRunner |
| `neo_mcp/evaluation/regression.py` | BaselineStore, JsonBaselineStore, RegressionDetector, RegressionVerdict |
| `neo_mcp/evaluation/review.py` | ReviewQueue, InMemoryReviewQueue, ReviewItem |
| `neo_mcp/evaluation/eval_instrumentation.py` | EvalInstrumentation, EVAL_FAILURE_PATTERNS |
| `neo_mcp/evaluation/eval_demo.py` | End-to-end demo |
| `neo_mcp/tests/evaluation/__init__.py` | Test package marker |
| `neo_mcp/tests/evaluation/test_datasets.py` | Dataset unit tests |
| `neo_mcp/tests/evaluation/test_scoring.py` | Scoring unit tests |
| `neo_mcp/tests/evaluation/test_runner.py` | Runner unit tests (fake agent) |
| `neo_mcp/tests/evaluation/test_regression.py` | Regression unit tests |
| `neo_mcp/tests/evaluation/test_review.py` | Review queue tests |
| `neo_mcp/tests/evaluation/test_eval_instrumentation.py` | Eval instrumentation tests |
| `docs/EVALUATION.md` | Architecture documentation |

## Success Criteria
- Full test suite passes: `pytest neo_mcp/tests/ -v` — 0 failures, 0 errors (original 137 + new eval tests)
- `python -m neo_mcp.evaluation.eval_demo` runs and visibly shows: dataset → batch run → scoring → aggregation → baseline → regression verdict → review queue
- Zero changes to any core file (confirmed by git diff or file listing)
- New test count reported