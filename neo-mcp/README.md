# neo-mcp: Self-Healing AI Agent Platform

A production-grade, self-healing AI agent **platform** with pluggable planning engines, structured recovery as an explicit state machine, dedicated failure classification, argument repair, output verification, and built-in observability.

## Architecture

The platform separates concerns into five independently replaceable subsystems:

```
┌─────────────────────────────────────────────────────────┐
│                   Agent Orchestrator                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Planner  │→ │ Executor │→ │ RecoveryOrchestrator │   │
│  └─────────┘  └──────────┘  └──────────────────────┘   │
│       │            │              │                      │
│       ▼            ▼              ▼                      │
│  ┌──────────┐ ┌──────────┐ ┌───────────────┐            │
│  │LLMPlanner│ │ToolExec  │ │FailClassifier │            │
│  │FixedPlan │ │ToolReg   │ │ArgRepairer    │            │
│  └──────────┘ └──────────┘ │OutputVerifier │            │
│                            │RecoveryStrat  │            │
│                            └───────────────┘            │
│       ┌──────────────────────────────────────┐          │
│       │      Instrumentation Layer            │          │
│       │  (Traces · Metrics · Structured Logs) │          │
│       └──────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

## Recovery State Machine

When a step fails, the platform follows an explicit state machine — not inline try/except:

```
Step Execution → ERROR
  → 1. Classify (FailureClassifier)
  → 2. Strategy Decision (RecoveryStrategy)
        ├── TRANSIENT: RETRY with exponential backoff → VERIFY → LOG
        ├── REPAIRABLE: REPAIR arguments → RETRY → VERIFY → LOG
        ├── ESCALATABLE: ESCALATE (log incident, halt or skip step)
        └── PERMANENT/UNKNOWN: FAIL gracefully → LOG
  → 3. Output Verification post-recovery
  → 4. Incident record persisted
```

## Core Modules

| Module | Path | Description |
|--------|------|-------------|
| **Core Models** | `neo_mcp/core/models.py` | Data models: `Step`, `Plan`, `StepResult`, `FailureCategory`, `RecoveryAction`, `Verdict`, `IncidentRecord` |
| **Interfaces** | `neo_mcp/core/interfaces.py` | ABCs for `Planner`, `Executor`, `FailureClassifier`, `ArgumentRepairer`, `OutputVerifier`, `RecoveryStrategy`, `LLMProvider`, `Instrumentation` |
| **Observability** | `neo_mcp/observability/instrumentation.py` | `ConsoleInstrumentation` with structured JSON logging, metrics counters, trace recording |
| **Failure Classifier** | `neo_mcp/recovery/failure_classifier.py` | `RuleBasedFailureClassifier` — pattern-matches errors to `FailureCategory` |
| **Recovery Strategies** | `neo_mcp/recovery/strategies.py` | `ExponentialBackoffStrategy`, `RepairAndRetryStrategy`, `EscalateStrategy`, `FailStrategy` |
| **Argument Repair** | `neo_mcp/recovery/argument_repairer.py` | `LLMArgumentRepairer` (uses LLM to fix malformed args), `NullArgumentRepairer` (no-op) |
| **Output Verifier** | `neo_mcp/recovery/output_verifier.py` | `SchemaOutputVerifier` (validates output against schema), `PassThroughVerifier` |
| **Recovery Orchestrator** | `neo_mcp/recovery/orchestrator.py` | State machine tying classifier → strategy → repair → retry → verify |
| **Tool Registry** | `neo_mcp/executor/registry.py` | `ToolRegistry` (register tools with name, function, schema), `ToolExecutor` (dispatch) |
| **Planners** | `neo_mcp/planners/` | `FixedPlanner` (deterministic), `LLMPlanner` (uses LLM to generate plans) |
| **Agent** | `neo_mcp/agent/orchestrator.py` | `SelfHealingAgent` — ties Planner + Executor + RecoveryOrchestrator + Instrumentation |

## Quick Start

### Prerequisites

- Python 3.12+
- An API key from Anthropic (set `ANTHROPIC_API_KEY` in environment or `.env`)

### Installation

```bash
git clone <repo-url>
cd neo-mcp

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install anthropic python-dotenv pytest
```

### Configuration

Copy or set environment variables:

```bash
# Required for LLM-backed components
export ANTHROPIC_API_KEY=sk-...

# Optional: Override model IDs
export PLANNER_MODEL_ID=claude-opus-4-8
export FAILURE_CLASSIFIER_MODEL_ID=claude-haiku-4-5-20251001

# Optional: Recovery tuning
export MAX_RECOVERY_ATTEMPTS=5
export BASE_BACKOFF_DELAY=0.5
```

Or create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-...
PLANNER_MODEL_ID=claude-opus-4-8
FAILURE_CLASSIFIER_MODEL_ID=claude-haiku-4-5-20251001
```

### Run the Demo

```bash
source venv/bin/activate
python -m neo_mcp.demos.demo_runner
```

The demo runs a 7-step task with flaky/controlled tools:

- `get_weather` — hits rate limit every 3rd call (TRANSIENT → RETRY)
- `query_database` — schema-violating args 40% (PERMANENT_BAD_ARGS → REPAIR_AND_RETRY)
- `validate_report` — output fails schema 30% (output-verification-fails-then-recovers path)
- `calculate` — random timeout 30% (TRANSIENT → RETRY)
- `send_email` — always works (control tool)

### Run Tests

```bash
source venv/bin/activate
pytest neo_mcp/tests/ -v
```

All 137 tests pass with 0 failures using fakes/mocks — no real API calls in unit tests.

## Extending the Platform

### Adding a New Planner

1. Implement the `Planner` interface (`neo_mcp/core/interfaces.py`):

```python
from neo_mcp.core.interfaces import Planner
from neo_mcp.core.models import Plan

class CustomPlanner(Planner):
    async def plan(self, goal: str, tool_descriptions: dict) -> Plan:
        # Your planning logic here
        return Plan(goal=goal, steps=[...])
```

2. Pass it to the agent:

```python
agent = SelfHealingAgent(
    planner=CustomPlanner(),
    executor=executor,
    recovery_orchestrator=recovery,
    instrumentation=instrumentation,
)
```

### Adding a New Recovery Strategy

1. Implement the `RecoveryStrategy` interface:

```python
from neo_mcp.core.interfaces import RecoveryStrategy
from neo_mcp.core.models import RecoveryAction, Step

class CustomStrategy(RecoveryStrategy):
    def get_action(self) -> RecoveryAction:
        return RecoveryAction.RETRY

    async def apply(self, step, error_message, attempt_number, **kwargs):
        # Custom recovery logic
        return step  # or None if recovery not possible
```

2. Register it with the orchestrator:

```python
strategies = {
    RecoveryAction.RETRY: CustomStrategy(),
    # ... other strategies
}
orchestrator = RecoveryOrchestrator(
    classifier=classifier,
    strategies=strategies,
    executor=executor,
    output_verifier=output_verifier,
)
```

## Failure Categories

| Category | Action | Examples |
|----------|--------|---------|
| `TRANSIENT` | RETRY | rate_limit, timeout, network_error, 503 |
| `PERMANENT_BAD_ARGS` | REPAIR_AND_RETRY | schema_violation, missing_required_param, type_error |
| `PERMANENT_AUTH` | FAIL | 401, 403, invalid API key |
| `PERMANENT_DOWNSTREAM` | ESCALATE | downstream_service_error, 500 |
| `UNKNOWN` | FAIL | Unclassifiable errors |

## Interface Overview

All interfaces are defined in `neo_mcp/core/interfaces.py`. Key methods:

```python
class Planner(ABC):
    async def plan(self, goal: str, tool_descriptions: list) -> Plan: ...

class Executor(ABC):
    async def execute_step(self, step: Step) -> StepResult: ...

class FailureClassifier(ABC):
    def classify(self, error_message: str, exception_type: Optional[str]) -> FailureClassification: ...

class ArgumentRepairer(ABC):
    async def repair_arguments(self, tool_name: str, arguments: dict, error_message: str, tool_schema: Optional[dict]) -> dict: ...

class OutputVerifier(ABC):
    def verify(self, output: Any, step: Step, output_schema: Optional[dict]) -> bool: ...

class RecoveryStrategy(ABC):
    def get_action(self) -> RecoveryAction: ...
    async def apply(self, step: Step, error_message: str, attempt_number: int, **kwargs) -> Optional[Step]: ...

class LLMProvider(ABC):
    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> str: ...

class Instrumentation(ABC):
    def log(self, level: str, message: str, **context) -> None: ...
    def increment(self, metric_name: str, value: int = 1, **tags) -> None: ...
    def record_trace(self, step_id: str, event: str, duration_ms: float, **attributes) -> None: ...
```

## Project Structure

```
neo-mcp/
├── neo_mcp/
│   ├── __init__.py
│   ├── config.py                   # Dataclass-based configuration
│   ├── agent/
│   │   └── orchestrator.py         # SelfHealingAgent
│   ├── core/
│   │   ├── models.py               # Data models
│   │   └── interfaces.py           # Abstract base classes
│   ├── demos/
│   │   ├── demo_runner.py          # E2E demo
│   │   └── demo_tools.py           # Flaky/controlled demo tools
│   ├── executor/
│   │   └── registry.py             # ToolRegistry and ToolExecutor
│   ├── observability/
│   │   └── instrumentation.py      # ConsoleInstrumentation
│   ├── planners/
│   │   ├── fixed_planner.py        # Deterministic planner
│   │   ├── llm_planner.py          # LLM-based planner
│   │   └── llm_provider.py         # LLM provider implementations
│   ├── recovery/
│   │   ├── argument_repairer.py    # Argument repair implementations
│   │   ├── failure_classifier.py   # Rule-based failure classifier
│   │   ├── orchestrator.py         # RecoveryOrchestrator
│   │   ├── output_verifier.py      # Output verification implementations
│   │   └── strategies.py           # Recovery strategy implementations
│   └── tests/                      # Full test suite (137 tests)
├── pytest.ini
├── README.md
└── .env                            # (optional — not committed)
```