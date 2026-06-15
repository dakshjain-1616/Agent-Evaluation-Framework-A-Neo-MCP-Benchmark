"""Unit tests for regression detection module."""

import json
import tempfile
from pathlib import Path

import pytest

from neo_mcp.evaluation.regression import (
    BaselineEntry,
    BaselineStore,
    JsonBaselineStore,
    RegressionDetector,
    RegressionVerdict,
)


class TestBaselineEntry:
    """Test BaselineEntry dataclass."""

    def test_defaults(self):
        entry = BaselineEntry(metric_name="exact_match", score=0.95)
        assert entry.metric_name == "exact_match"
        assert entry.score == 0.95
        assert entry.threshold == 0.05
        assert entry.run_id == ""
        assert entry.timestamp == ""


class TestBaselineStore:
    """Test BaselineStore ABC cannot be instantiated."""

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaselineStore()  # type: ignore


class TestJsonBaselineStore:
    """Test JsonBaselineStore implementation."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        self.tmp.write("[]")
        self.tmp.close()
        self.store = JsonBaselineStore(filepath=self.tmp.name)

    def teardown_method(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_save_and_load(self):
        entry = BaselineEntry(
            metric_name="exact_match",
            score=0.95,
            threshold=0.1,
            run_id="test_run",
        )
        self.store.save(entry)

        loaded = self.store.load("exact_match")
        assert loaded is not None
        assert loaded.metric_name == "exact_match"
        assert loaded.score == 0.95
        assert loaded.threshold == 0.1
        assert loaded.run_id == "test_run"
        assert loaded.timestamp != ""

    def test_load_nonexistent(self):
        loaded = self.store.load("nonexistent")
        assert loaded is None

    def test_list_baselines(self):
        entries = [
            BaselineEntry(metric_name="m1", score=0.9),
            BaselineEntry(metric_name="m2", score=0.8),
        ]
        for e in entries:
            self.store.save(e)

        listed = self.store.list_baselines()
        assert len(listed) == 2
        names = {e.metric_name for e in listed}
        assert "m1" in names
        assert "m2" in names

    def test_clear(self):
        self.store.save(BaselineEntry(metric_name="m1", score=0.9))
        self.store.clear()

        assert self.store.load("m1") is None
        assert not Path(self.tmp.name).exists()

    def test_overwrite_same_metric(self):
        self.store.save(BaselineEntry(metric_name="m1", score=0.9))
        self.store.save(BaselineEntry(metric_name="m1", score=0.95))

        loaded = self.store.load("m1")
        assert loaded.score == 0.95

    def test_persistence_across_instances(self):
        """Test that data persists when creating a new store pointing to same file."""
        self.store.save(BaselineEntry(metric_name="m1", score=0.9))

        store2 = JsonBaselineStore(filepath=self.tmp.name)
        loaded = store2.load("m1")
        assert loaded is not None
        assert loaded.score == 0.9

    def test_load_from_corrupted_file(self):
        with open(self.tmp.name, "w") as f:
            f.write("not valid json")

        store = JsonBaselineStore(filepath=self.tmp.name)
        store._load_from_disk()  # Should not raise
        assert store.list_baselines() == []


class TestRegressionDetector:
    """Test RegressionDetector logic."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        self.tmp.write("[]")
        self.tmp.close()
        self.store = JsonBaselineStore(filepath=self.tmp.name)
        self.detector = RegressionDetector(
            baseline_store=self.store, default_threshold=0.1
        )

    def teardown_method(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_no_baseline_skips_comparison(self):
        """If no baseline exists for a metric, no verdict is returned."""
        summary = {"exact_match": {"mean": 0.5}}
        verdicts = await self.detector.compare(summary)
        assert verdicts == []  # No baseline → skip

    @pytest.mark.asyncio
    async def test_regression_detected_score_decreased(self):
        await self.detector.save_baseline({"exact_match": {"mean": 0.95}})
        verdicts = await self.detector.compare({"exact_match": {"mean": 0.5}})

        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.passed is False
        assert v.regression_type == "score_decreased"
        assert v.metric_name == "exact_match"
        assert v.current_score == 0.5
        assert v.baseline_score == 0.95
        assert v.delta == -0.45

    @pytest.mark.asyncio
    async def test_no_regression_within_threshold(self):
        await self.detector.save_baseline({"exact_match": {"mean": 0.95}})
        # Within threshold (0.1): current=0.92, baseline=0.95, delta=-0.03
        verdicts = await self.detector.compare({"exact_match": {"mean": 0.92}})

        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.passed is True
        assert v.regression_type == ""
        assert "No regression detected" in v.details

    @pytest.mark.asyncio
    async def test_improvement_detected(self):
        await self.detector.save_baseline({"exact_match": {"mean": 0.5}})
        verdicts = await self.detector.compare({"exact_match": {"mean": 0.95}})

        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.passed is True
        assert v.regression_type == "score_increased"
        assert v.delta == 0.45

    @pytest.mark.asyncio
    async def test_save_baseline_with_run_id(self):
        await self.detector.save_baseline(
            {"exact_match": {"mean": 0.95}},
            run_id="run_001",
        )
        entry = self.store.load("exact_match")
        assert entry.run_id == "run_001"

    @pytest.mark.asyncio
    async def test_per_metric_thresholds(self):
        detector = RegressionDetector(
            baseline_store=self.store,
            default_threshold=0.1,
            metric_thresholds={"exact_match": 0.2},
        )
        await detector.save_baseline({"exact_match": {"mean": 0.95}})

        # Within per-metric threshold (0.2) but below default (0.1)
        verdicts = await detector.compare({"exact_match": {"mean": 0.80}})
        assert len(verdicts) == 1
        assert verdicts[0].passed is True  # delta=-0.15, threshold=0.2 → no regression

    @pytest.mark.asyncio
    async def test_multiple_metrics(self):
        await self.detector.save_baseline({
            "m1": {"mean": 0.9},
            "m2": {"mean": 0.8},
        })
        verdicts = await self.detector.compare({
            "m1": {"mean": 0.5},  # Regression
            "m2": {"mean": 0.85},  # Within threshold
        })

        assert len(verdicts) == 2
        m1_verdicts = [v for v in verdicts if v.metric_name == "m1"]
        m2_verdicts = [v for v in verdicts if v.metric_name == "m2"]
        assert m1_verdicts[0].passed is False
        assert m2_verdicts[0].passed is True


class TestRegressionVerdict:
    """Test RegressionVerdict dataclass."""

    def test_default_values(self):
        v = RegressionVerdict()
        assert v.passed is True
        assert v.regression_type == ""
        assert v.threshold == 0.05