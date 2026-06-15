"""Unit tests for evaluation datasets module."""

import json
import tempfile
from pathlib import Path

import pytest

from neo_mcp.evaluation.datasets import (
    EvaluationCase,
    EvaluationDataset,
    InMemoryDataset,
    JsonlDataset,
)


class TestEvaluationCase:
    """Test EvaluationCase dataclass creation and attributes."""

    def test_create_basic(self):
        case = EvaluationCase(
            case_id="test_1",
            goal="Do something",
            expected_output="result",
        )
        assert case.case_id == "test_1"
        assert case.goal == "Do something"
        assert case.expected_output == "result"
        assert case.metadata == {}

    def test_create_with_metadata(self):
        case = EvaluationCase(
            case_id="test_2",
            goal="Another task",
            expected_output="output",
            metadata={"difficulty": "hard", "category": "math"},
        )
        assert case.metadata["difficulty"] == "hard"
        assert case.metadata["category"] == "math"


class TestInMemoryDataset:
    """Test InMemoryDataset implementation."""

    def test_empty_dataset(self):
        dataset = InMemoryDataset(cases=[], version="0.0.1")
        dataset.load()
        assert dataset.all_cases() == []

    def test_with_cases(self):
        cases = [
            EvaluationCase(case_id="a", goal="Goal A", expected_output="A"),
            EvaluationCase(case_id="b", goal="Goal B", expected_output="B"),
        ]
        dataset = InMemoryDataset(cases=cases, version="1.0.0")
        dataset.load()
        assert len(dataset.all_cases()) == 2
        assert dataset.version() == "1.0.0"

    def test_sample(self):
        cases = [
            EvaluationCase(case_id=f"case_{i}", goal=f"Goal {i}", expected_output=str(i))
            for i in range(10)
        ]
        dataset = InMemoryDataset(cases=cases, version="1.0.0")
        dataset.load()

        sampled = dataset.sample(n=3, seed=42)
        assert len(sampled) == 3
        assert all(c.case_id in {c.case_id for c in cases} for c in sampled)

        # Deterministic with same seed
        sampled2 = dataset.sample(n=3, seed=42)
        assert [c.case_id for c in sampled] == [c.case_id for c in sampled2]

    def test_sample_more_than_available(self):
        cases = [EvaluationCase(case_id="a", goal="A", expected_output="a")]
        dataset = InMemoryDataset(cases=cases, version="1.0.0")
        dataset.load()
        sampled = dataset.sample(n=5, seed=42)
        assert len(sampled) == 1  # Returns all available

    def test_split(self):
        cases = [
            EvaluationCase(case_id=f"case_{i}", goal=f"Goal {i}", expected_output=str(i))
            for i in range(10)
        ]
        dataset = InMemoryDataset(cases=cases, version="1.0.0")
        dataset.load()

        train, test = dataset.split(train_ratio=0.7, seed=42)
        assert len(train) + len(test) == 10
        assert len(train) == 7
        assert len(test) == 3
        # No overlap
        train_ids = {c.case_id for c in train}
        test_ids = {c.case_id for c in test}
        assert train_ids.isdisjoint(test_ids)

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            EvaluationDataset()  # type: ignore


class TestJsonlDataset:
    """Test JsonlDataset implementation."""

    def test_load_from_jsonl(self):
        cases_data = [
            {"case_id": "1", "goal": "Goal 1", "expected_output": "out1", "metadata": {"k": "v1"}},
            {"case_id": "2", "goal": "Goal 2", "expected_output": "out2", "metadata": {"k": "v2"}},
        ]

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            for c in cases_data:
                f.write(json.dumps(c) + "\n")
            fpath = f.name

        try:
            dataset = JsonlDataset(filepath=fpath)
            dataset.load()
            cases = dataset.all_cases()
            assert len(cases) == 2
            assert cases[0].case_id == "1"
            assert cases[0].goal == "Goal 1"
            assert cases[0].expected_output == "out1"
            assert cases[0].metadata == {"k": "v1"}
            assert cases[1].case_id == "2"
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_load_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            fpath = f.name

        try:
            dataset = JsonlDataset(filepath=fpath)
            dataset.load()
            assert dataset.all_cases() == []
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_version_from_filename(self):
        """Test that JsonlDataset extracts version from filename (e.g., v1.0.0)."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            fpath = f.name

        try:
            # No version in path
            dataset = JsonlDataset(filepath=fpath)
            assert dataset.version() == "unknown"
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_load_with_malformed_line(self):
        """Malformed JSON lines should be skipped gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write('{"case_id": "1", "goal": "G1", "expected_output": "o1"}\n')
            f.write('not-valid-json\n')
            f.write('{"case_id": "2", "goal": "G2", "expected_output": "o2"}\n')
            fpath = f.name

        try:
            dataset = JsonlDataset(filepath=fpath)
            dataset.load()
            cases = dataset.all_cases()
            assert len(cases) == 2  # Malformed line skipped
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_sample_and_split_on_jsonl(self):
        cases_data = [
            {"case_id": str(i), "goal": f"Goal {i}", "expected_output": f"out{i}"}
            for i in range(10)
        ]

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            for c in cases_data:
                f.write(json.dumps(c) + "\n")
            fpath = f.name

        try:
            dataset = JsonlDataset(filepath=fpath)
            dataset.load()

            sampled = dataset.sample(n=3, seed=42)
            assert len(sampled) == 3

            train, test = dataset.split(train_ratio=0.8, seed=42)
            assert len(train) == 8
            assert len(test) == 2
        finally:
            Path(fpath).unlink(missing_ok=True)