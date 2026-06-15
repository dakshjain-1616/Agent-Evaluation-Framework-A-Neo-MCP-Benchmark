# Evaluation Layer Architecture

The `neo_mcp.evaluation` package provides a structured framework for running
`SelfHealingAgent` evaluations over datasets, scoring results, detecting
regressions, and managing human review queues.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Evaluation Layer                             │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │
│  │ Datasets │  │ Scoring  │  │ Runner   │  │ Regression     │ │
│  │          │  │          │  │          │  │ Detection      │ │
│  │ • Cases  │  │ • Metrics│  │ • Agent  │  │                │ │
│  │ • Load   │──│ • Aggreg │──│ Factory  │──│ • Baseline     │ │
│  │ • Split  │  │   ator   │  │ • Concur │  │ • Thresholds   │ │
│  │ • Sample │  │          │  │   rency  │  │ • Verdicts     │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘ │
│                                     │                           │
│                                     ▼                           │
│  ┌────────────────┐  ┌──────────────────────────────────────┐  │
│  │ Review Queue   │  │ Eval Instrumentation                 │  │
│  │                │  │                                      │  │
│  │ • Enqueue      │  │ • Composes with ConsoleInstr         │  │
│  │ • Pending      │  │ • EVAL_FAILURE_PATTERNS              │  │
│  │ • Resolve      │  │ • extend_failure_classifier()        │  │
│  └────────────────┘  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Core Layer (unchanged)                       │
│                                                                  │
│  SelfHealingAgent → Planner → Executor → RecoveryOrchestrator   │
│                        → Instrumentation                         │
└─────────────────────────────────────────────────────────────────┘
```

## Modules

### 1. Datasets (`neo_mcp/evaluation/datasets.py`)

**Purpose**: Define evaluation cases and manage datasets.

**Key types**:
- `EvaluationCase`: A single test case with `case_id`, `goal`, `expected_output`, and `metadata`.
- `EvaluationDataset` (ABC): Interface for loading, sampling, splitting, and versioning datasets.
- `InMemoryDataset`: Holds cases in memory — useful for testing and demos.
- `JsonlDataset`: Reads cases from a JSONL file, line by line.

**Usage**:
```python
from neo_mcp.evaluation.datasets import EvaluationCase, InMemoryDataset

cases = [
    EvaluationCase(case_id="1", goal="Get weather for London",
                   expected_output="London: 15°C"),
]
dataset = InMemoryDataset(cases=cases, version="1.0.0")
dataset.load()
cases = dataset.all_cases()
train, test = dataset.split(train_ratio=0.8, seed=42)
sample = dataset.sample(n=3, seed=42)
```

### 2. Scoring (`neo_mcp/evaluation/scoring.py`)

**Purpose**: Score agent results against expected outputs using configurable metrics.

**Key types**:
- `MetricResult`: Holds a single metric's score, details, and success flag.
- `EvaluationMetric` (ABC): Interface for scoring a case against an agent result.
- `ExactMatchMetric`: 1.0 if `agent_result.summary == case.expected_output`, else 0.0.
- `SuccessRateMetric`: 1.0 if `agent_result.success` is True, else 0.0.
- `LatencyMetric`: Returns total step duration in seconds (informational).
- `RecoveryCountMetric`: Returns number of incidents (lower is better).
- `ScoreAggregator`: Rolls per-case metric results into run-level summary statistics
  (mean, min, max, std, success_rate).

**Usage**:
```python
from neo_mcp.evaluation.scoring import (
    ExactMatchMetric, SuccessRateMetric, LatencyMetric,
    RecoveryCountMetric, ScoreAggregator,
)

metrics = [ExactMatchMetric(), SuccessRateMetric(), LatencyMetric()]
aggregator = ScoreAggregator()
summary = aggregator.aggregate(all_metric_results)
```

### 3. Runner (`neo_mcp/evaluation/runner.py`)

**Purpose**: Orchestrate running SelfHealingAgent over a dataset with concurrency control.

**Key types**:
- `EvaluationReport`: Complete report including per-case results, aggregated summary,
  config, dataset version, duration, and success counts.
- `EvaluationRunner`: Takes an agent factory (callable returning SelfHealingAgent),
  dataset, metrics, and optional concurrency/seed parameters.

**Features**:
- Bounded asyncio concurrency via `asyncio.Semaphore`.
- Seedable for deterministic test runs.
- Graceful failure handling: errors in agent execution or metric scoring never
  crash the entire evaluation — individual case errors are recorded.
- Configurable case filtering.

**Usage**:
```python
from neo_mcp.evaluation.runner import EvaluationRunner

runner = EvaluationRunner(
    agent_factory=lambda: create_my_agent(),
    dataset=my_dataset,
    metrics=[ExactMatchMetric(), SuccessRateMetric()],
    max_concurrency=3,
    seed=42,
)
report = await runner.run()
```

### 4. Regression Detection (`neo_mcp/evaluation/regression.py`)

**Purpose**: Compare current evaluation results against stored baselines to detect
performance regressions.

**Key types**:
- `BaselineEntry`: A single metric's baseline value with configurable threshold.
- `BaselineStore` (ABC): Interface for persisting baselines.
- `JsonBaselineStore`: File-backed store using JSON.
- `RegressionDetector`: Compares current aggregated scores against baselines,
  producing `RegressionVerdict` objects.
- `RegressionVerdict`: Contains pass/fail, regression type, delta, threshold, details.

**Features**:
- Per-metric threshold configurability.
- Detects both regressions (score decreased) and improvements (score increased).
- Scores within threshold are treated as neutral (no regression).

**Usage**:
```python
from neo_mcp.evaluation.regression import (
    JsonBaselineStore, RegressionDetector,
)

store = JsonBaselineStore(filepath="baselines.json")
detector = RegressionDetector(baseline_store=store, default_threshold=0.05)

# Save baseline
await detector.save_baseline(aggregated_summary, run_id="run_001")

# Detect regressions
verdicts = await detector.compare(current_aggregated_summary)
```

### 5. Human Review Hook (`neo_mcp/evaluation/review.py`)

**Purpose**: Flag evaluation results for human review.

**Key types**:
- `ReviewStatus` (Enum): PENDING, APPROVED, REJECTED, REQUESTED_CHANGES.
- `ReviewEntry`: Data for a review item including score, details, status, and reviewer notes.
- `ReviewQueue` (ABC): Interface for managing review queues.
- `InMemoryReviewQueue`: In-memory implementation for testing and demos.

**Usage**:
```python
from neo_mcp.evaluation.review import InMemoryReviewQueue, ReviewEntry, ReviewStatus

queue = InMemoryReviewQueue()
entry_id = queue.enqueue(ReviewEntry(case_id="c1", metric_name="exact_match", score=0.5))
pending = queue.pending()
queue.resolve(entry_id, ReviewStatus.APPROVED, "All good")
```

### 6. Eval Instrumentation (`neo_mcp/evaluation/eval_instrumentation.py`)

**Purpose**: Add evaluation-specific observability by composing with the existing
ConsoleInstrumentation (NOT forking/subclassing it).

**Key types**:
- `EvalEvent`: Structured event with type, case_id, metric_name, score, details, timestamp.
- `EvalInstrumentation`: Wraps ConsoleInstrumentation and adds evaluation-specific
  logging, event recording, and metric counters.
- `EVAL_FAILURE_PATTERNS`: A list of failure pattern dicts for use with
  `RuleBasedFailureClassifier` — demonstrates compositional extension.
- `extend_failure_classifier()`: Utility function that combines base classifier
  patterns with eval-specific patterns via composition.

**Usage**:
```python
from neo_mcp.observability.instrumentation import ConsoleInstrumentation
from neo_mcp.evaluation.eval_instrumentation import (
    EvalInstrumentation, EVAL_FAILURE_PATTERNS,
    extend_failure_classifier,
)
from neo_mcp.recovery.failure_classifier import RuleBasedFailureClassifier

# Compose with existing instrumentation
base = ConsoleInstrumentation()
eval_instr = EvalInstrumentation(instrumentation=base)
eval_instr.record_eval_event("run_start", case_id="all")

# Extend failure classifier without modifying it
classifier = RuleBasedFailureClassifier()
extended = extend_failure_classifier(classifier, EVAL_FAILURE_PATTERNS)
```

## Integration Points with Core

The evaluation layer imports and uses the following core types WITHOUT modifying them:

| Core Type | Source Module | Usage in Eval Layer |
|-----------|-------------|-------------------|
| `SelfHealingAgent` | `neo_mcp.agent.orchestrator` | Execution unit for running evaluation cases |
| `AgentResult` | `neo_mcp.agent.orchestrator` | Result type consumed by metrics |
| `ConsoleInstrumentation` | `neo_mcp.observability.instrumentation` | Composed into EvalInstrumentation |
| `RuleBasedFailureClassifier` | `neo_mcp.recovery.failure_classifier` | Extended via composition in eval_instrumentation |
| `FixedPlanner` | `neo_mcp.planners.fixed_planner` | Used in eval_demo for deterministic plans |
| `Plan`, `Step`, `StepResult`, `Verdict` | `neo_mcp.core.models` | Core data models |
| `ToolRegistry`, `ToolExecutor` | `neo_mcp.executor.registry` | Tool execution in demo |
| `RecoveryOrchestrator` | `neo_mcp.recovery.orchestrator` | Recovery setup in demo |

## Design Principles

1. **No modifications to core**: All evaluation types are additive. Zero changes to
   any existing file in `neo_mcp/core/`, `neo_mcp/recovery/`, `neo_mcp/planners/`,
   `neo_mcp/executor/`, `neo_mcp/agent/`, `neo_mcp/observability/`.

2. **ABCs for all interfaces**: Every component has an abstract base class with
   clean public interfaces, enabling easy testing and alternative implementations.

3. **Graceful failure handling**: The EvaluationRunner never crashes on individual
   case errors — errors are captured and recorded in the report.

4. **Composition over inheritance**: EvalInstrumentation composes with
   ConsoleInstrumentation rather than subclassing it. extend_failure_classifier
   demonstrates compositional extension of classifiers.

5. **Deterministic by default**: Seedable random operations for reproducible
   evaluations.

6. **No external dependencies**: Uses only Python stdlib and existing neo-mcp
   dependencies (anthropic, python-dotenv, pytest).

## Test Strategy

All tests in `neo_mcp/tests/evaluation/` use fakes and mocks:
- `FakeAgent`: Returns predetermined AgentResult without real execution.
- `FakeMetric`: Returns fixed MetricResult for testing aggregation.
- No real LLM calls or network requests.

Tests use pytest-asyncio style with `asyncio_mode = auto` in `pytest.ini`.