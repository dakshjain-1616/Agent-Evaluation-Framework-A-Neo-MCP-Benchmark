"""Regression detection — compares current evaluation results against baselines.

Provides BaselineStore ABC for persisting baselines, JsonBaselineStore for
JSON file-backed storage, and RegressionDetector for comparing current runs
against stored baselines with configurable thresholds.
"""

from __future__ import annotations

import abc
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class BaselineEntry:
    """A single metric's baseline value from a previous run.

    Attributes:
        metric_name: Name of the metric.
        score: The baseline score value.
        threshold: Acceptable deviation threshold for regression detection.
        run_id: Identifier of the run that produced this baseline.
        timestamp: When the baseline was recorded.
    """

    metric_name: str
    score: float
    threshold: float = 0.05
    run_id: str = ""
    timestamp: str = ""


class BaselineStore(abc.ABC):
    """Abstract interface for persisting evaluation baselines."""

    @abc.abstractmethod
    def save(self, entry: BaselineEntry) -> None:
        """Save a baseline entry.

        Args:
            entry: The baseline entry to persist.
        """
        ...

    @abc.abstractmethod
    def load(self, metric_name: str) -> Optional[BaselineEntry]:
        """Load a baseline entry by metric name.

        Args:
            metric_name: Name of the metric to load.

        Returns:
            BaselineEntry if found, None otherwise.
        """
        ...

    @abc.abstractmethod
    def list_baselines(self) -> List[BaselineEntry]:
        """List all stored baseline entries.

        Returns:
            List of all BaselineEntry objects.
        """
        ...

    @abc.abstractmethod
    def clear(self) -> None:
        """Clear all stored baselines."""
        ...


class JsonBaselineStore(BaselineStore):
    """Baseline store backed by a JSON file.

    All baselines are stored in a single JSON file as a list of entries.
    """

    def __init__(self, filepath: str) -> None:
        self._filepath = filepath
        self._entries: Dict[str, BaselineEntry] = {}
        self._load_from_disk()

    def save(self, entry: BaselineEntry) -> None:
        """Save a baseline entry to the JSON file."""
        if not entry.run_id:
            entry.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        if not entry.timestamp:
            entry.timestamp = datetime.now(timezone.utc).isoformat()

        self._entries[entry.metric_name] = entry
        self._flush()

    def load(self, metric_name: str) -> Optional[BaselineEntry]:
        """Load a baseline entry by metric name."""
        return self._entries.get(metric_name)

    def list_baselines(self) -> List[BaselineEntry]:
        """List all stored baseline entries."""
        return list(self._entries.values())

    def clear(self) -> None:
        """Clear all stored baselines."""
        self._entries.clear()
        if os.path.exists(self._filepath):
            os.remove(self._filepath)

    def _flush(self) -> None:
        """Write all entries to the JSON file."""
        data = [
            {
                "metric_name": e.metric_name,
                "score": e.score,
                "threshold": e.threshold,
                "run_id": e.run_id,
                "timestamp": e.timestamp,
            }
            for e in self._entries.values()
        ]
        with open(self._filepath, "w") as f:
            json.dump(data, f, indent=2)

    def _load_from_disk(self) -> None:
        """Load all entries from the JSON file."""
        if not os.path.exists(self._filepath):
            return
        try:
            with open(self._filepath, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return

        self._entries = {}
        for item in data:
            entry = BaselineEntry(
                metric_name=item["metric_name"],
                score=item["score"],
                threshold=item.get("threshold", 0.05),
                run_id=item.get("run_id", ""),
                timestamp=item.get("timestamp", ""),
            )
            self._entries[entry.metric_name] = entry


@dataclass
class RegressionVerdict:
    """The result of comparing a current score against a baseline.

    Attributes:
        passed: True if no regression was detected.
        regression_type: Type of regression found (e.g., 'score_decreased', 'score_increased', '').
        metric_name: Name of the metric being compared.
        current_score: The current run's score.
        baseline_score: The baseline score.
        delta: The difference (current - baseline).
        threshold: The threshold used for comparison.
        details: Optional human-readable explanation.
    """

    passed: bool = True
    regression_type: str = ""
    metric_name: str = ""
    current_score: float = 0.0
    baseline_score: float = 0.0
    delta: float = 0.0
    threshold: float = 0.05
    details: str = ""


class RegressionDetector:
    """Detects regressions by comparing current evaluation metrics against baselines.

    Uses configurable per-metric thresholds. By default, a regression is flagged
    when the current score is below the baseline score by more than the threshold.
    """

    def __init__(
        self,
        baseline_store: BaselineStore,
        default_threshold: float = 0.05,
        metric_thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        self._baseline_store = baseline_store
        self._default_threshold = default_threshold
        self._metric_thresholds = metric_thresholds or {}

    async def compare(
        self,
        aggregated_summary: Dict[str, Dict[str, float]],
    ) -> List[RegressionVerdict]:
        """Compare current aggregated results against stored baselines.

        Args:
            aggregated_summary: Dict mapping metric_name -> {mean, min, max, std, count, success_rate}.

        Returns:
            List of RegressionVerdict objects, one per metric that has a baseline.
        """
        verdicts: List[RegressionVerdict] = []

        for metric_name, stats in aggregated_summary.items():
            current_score = stats.get("mean", 0.0)
            baseline_entry = self._baseline_store.load(metric_name)

            if baseline_entry is None:
                # No baseline yet — skip regression check
                continue

            threshold = self._metric_thresholds.get(
                metric_name, baseline_entry.threshold
            )
            delta = round(current_score - baseline_entry.score, 4)

            # Detect regression: current score is significantly lower than baseline
            if current_score < baseline_entry.score - threshold:
                verdicts.append(
                    RegressionVerdict(
                        passed=False,
                        regression_type="score_decreased",
                        metric_name=metric_name,
                        current_score=current_score,
                        baseline_score=baseline_entry.score,
                        delta=delta,
                        threshold=threshold,
                        details=(
                            f"Score decreased from {baseline_entry.score:.4f} "
                            f"to {current_score:.4f} (delta={delta:.4f}, "
                            f"threshold={threshold})"
                        ),
                    )
                )
            elif current_score > baseline_entry.score + threshold:
                # Improvement detected
                verdicts.append(
                    RegressionVerdict(
                        passed=True,
                        regression_type="score_increased",
                        metric_name=metric_name,
                        current_score=current_score,
                        baseline_score=baseline_entry.score,
                        delta=delta,
                        threshold=threshold,
                        details=(
                            f"Score improved from {baseline_entry.score:.4f} "
                            f"to {current_score:.4f} (delta={delta:.4f}, "
                            f"threshold={threshold})"
                        ),
                    )
                )
            else:
                # Within threshold — no regression
                verdicts.append(
                    RegressionVerdict(
                        passed=True,
                        regression_type="",
                        metric_name=metric_name,
                        current_score=current_score,
                        baseline_score=baseline_entry.score,
                        delta=delta,
                        threshold=threshold,
                        details="No regression detected (within threshold)",
                    )
                )

        return verdicts

    async def save_baseline(
        self,
        aggregated_summary: Dict[str, Dict[str, float]],
        run_id: str = "",
        thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        """Save current results as a new baseline.

        Args:
            aggregated_summary: Dict mapping metric_name -> {mean, ...}.
            run_id: Optional identifier for this run.
            thresholds: Optional per-metric thresholds to override defaults.
        """
        thresholds = thresholds or {}
        for metric_name, stats in aggregated_summary.items():
            entry = BaselineEntry(
                metric_name=metric_name,
                score=stats.get("mean", 0.0),
                threshold=thresholds.get(metric_name, self._default_threshold),
                run_id=run_id,
            )
            self._baseline_store.save(entry)