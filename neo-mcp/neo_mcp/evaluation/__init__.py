"""Evaluation layer for the neo-mcp self-healing agent platform.

This package provides tools for running SelfHealingAgent evaluations
over datasets, scoring results, detecting regressions, and managing
human review queues.
"""

from neo_mcp.evaluation.datasets import (
    EvaluationCase,
    EvaluationDataset,
    InMemoryDataset,
    JsonlDataset,
)
from neo_mcp.evaluation.scoring import (
    MetricResult,
    EvaluationMetric,
    ExactMatchMetric,
    SuccessRateMetric,
    LatencyMetric,
    RecoveryCountMetric,
    ScoreAggregator,
)
from neo_mcp.evaluation.runner import EvaluationRunner, EvaluationReport
from neo_mcp.evaluation.regression import (
    BaselineStore,
    JsonBaselineStore,
    RegressionVerdict,
    RegressionDetector,
)
from neo_mcp.evaluation.review import ReviewQueue, ReviewEntry, InMemoryReviewQueue
from neo_mcp.evaluation.eval_instrumentation import (
    EvalInstrumentation,
    EVAL_FAILURE_PATTERNS,
)

__all__ = [
    # datasets
    "EvaluationCase",
    "EvaluationDataset",
    "InMemoryDataset",
    "JsonlDataset",
    # scoring
    "MetricResult",
    "EvaluationMetric",
    "ExactMatchMetric",
    "SuccessRateMetric",
    "LatencyMetric",
    "RecoveryCountMetric",
    "ScoreAggregator",
    # runner
    "EvaluationRunner",
    "EvaluationReport",
    # regression
    "BaselineStore",
    "JsonBaselineStore",
    "RegressionVerdict",
    "RegressionDetector",
    # review
    "ReviewQueue",
    "ReviewEntry",
    "InMemoryReviewQueue",
    # instrumentation
    "EvalInstrumentation",
    "EVAL_FAILURE_PATTERNS",
]