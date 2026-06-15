"""Evaluation datasets — data structures for test cases.

Provides EvaluationCase for individual test cases, and EvaluationDataset
abstract interface for loading, sampling, splitting, and versioning datasets.
"""

from __future__ import annotations

import abc
import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EvaluationCase:
    """A single evaluation test case.

    Attributes:
        case_id: Unique identifier for this case.
        goal: The input/goal string to pass to SelfHealingAgent.run().
        expected_output: The expected output or criteria for scoring.
        metadata: Optional dict of additional metadata (tags, difficulty, etc.).
    """

    case_id: str
    goal: str
    expected_output: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class EvaluationDataset(abc.ABC):
    """Abstract base class for evaluation datasets.

    Provides load, sample, split, and version operations.
    """

    @abc.abstractmethod
    def load(self) -> None:
        """Load the dataset into memory.

        Must be called before sample() or split().
        """
        ...

    @abc.abstractmethod
    def sample(self, n: int, seed: Optional[int] = None) -> List[EvaluationCase]:
        """Randomly sample n cases from the dataset.

        Args:
            n: Number of cases to sample.
            seed: Optional random seed for reproducibility.

        Returns:
            List of sampled EvaluationCase objects.
        """
        ...

    @abc.abstractmethod
    def split(
        self,
        train_ratio: float = 0.8,
        seed: Optional[int] = None,
    ) -> Tuple[List[EvaluationCase], List[EvaluationCase]]:
        """Split the dataset into train and test subsets.

        Args:
            train_ratio: Proportion of cases for training (0.0 to 1.0).
            seed: Optional random seed for reproducibility.

        Returns:
            Tuple of (train_cases, test_cases).
        """
        ...

    @abc.abstractmethod
    def version(self) -> str:
        """Return the version identifier for this dataset.

        Returns:
            String version identifier.
        """
        ...

    @abc.abstractmethod
    def all_cases(self) -> List[EvaluationCase]:
        """Return all loaded cases.

        Returns:
            List of all EvaluationCase objects currently loaded.
        """
        ...


class InMemoryDataset(EvaluationDataset):
    """A dataset backed by an in-memory list of EvaluationCase objects.

    Useful for testing and small-scale evaluations.
    """

    def __init__(
        self,
        cases: List[EvaluationCase],
        version: str = "1.0.0",
        dataset_name: str = "in-memory",
    ) -> None:
        self._cases = list(cases)
        self._version = version
        self._dataset_name = dataset_name
        self._loaded = True  # Already in memory

    def load(self) -> None:
        """Already loaded — no-op."""
        self._loaded = True

    def sample(self, n: int, seed: Optional[int] = None) -> List[EvaluationCase]:
        """Randomly sample n cases.

        If n exceeds the number of available cases, returns all cases.
        """
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        if n >= len(self._cases):
            return list(self._cases)
        rng = random.Random(seed)
        return rng.sample(self._cases, n)

    def split(
        self,
        train_ratio: float = 0.8,
        seed: Optional[int] = None,
    ) -> Tuple[List[EvaluationCase], List[EvaluationCase]]:
        """Split dataset into train/test subsets."""
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        if not 0.0 < train_ratio < 1.0:
            raise ValueError("train_ratio must be between 0.0 and 1.0 (exclusive)")
        rng = random.Random(seed)
        shuffled = list(self._cases)
        rng.shuffle(shuffled)
        split_idx = int(len(shuffled) * train_ratio)
        return shuffled[:split_idx], shuffled[split_idx:]

    def version(self) -> str:
        """Return the dataset version."""
        return self._version

    def all_cases(self) -> List[EvaluationCase]:
        """Return all loaded cases."""
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        return list(self._cases)

    def add_case(self, case: EvaluationCase) -> None:
        """Add a single case to the dataset (mutates in-place)."""
        self._cases.append(case)

    @property
    def name(self) -> str:
        """Return the dataset name."""
        return self._dataset_name


class JsonlDataset(EvaluationDataset):
    """A dataset backed by a JSONL file (one JSON object per line).

    Each line should contain at minimum 'case_id', 'goal', and 'expected_output' fields.
    An optional 'metadata' field is also supported.
    """

    def __init__(
        self,
        filepath: str,
        version: str = "unknown",
        dataset_name: str = "",
    ) -> None:
        self._filepath = filepath
        self._version = version
        self._dataset_name = dataset_name or f"jsonl:{filepath}"
        self._cases: List[EvaluationCase] = []
        self._loaded = False

    def load(self) -> None:
        """Load cases from the JSONL file, skipping malformed lines."""
        self._cases = []
        with open(self._filepath, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Skip malformed JSON lines gracefully
                    continue

                if "case_id" not in data or "goal" not in data or "expected_output" not in data:
                    # Skip lines missing required fields
                    continue

                case = EvaluationCase(
                    case_id=str(data["case_id"]),
                    goal=str(data["goal"]),
                    expected_output=str(data["expected_output"]),
                    metadata=data.get("metadata", {}),
                )
                self._cases.append(case)

        self._loaded = True

    def sample(self, n: int, seed: Optional[int] = None) -> List[EvaluationCase]:
        """Randomly sample n cases."""
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        if n > len(self._cases):
            raise ValueError(
                f"Cannot sample {n} cases from dataset with {len(self._cases)} cases"
            )
        rng = random.Random(seed)
        return rng.sample(self._cases, n)

    def split(
        self,
        train_ratio: float = 0.8,
        seed: Optional[int] = None,
    ) -> Tuple[List[EvaluationCase], List[EvaluationCase]]:
        """Split dataset into train/test subsets."""
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        if not 0.0 < train_ratio < 1.0:
            raise ValueError("train_ratio must be between 0.0 and 1.0 (exclusive)")
        rng = random.Random(seed)
        shuffled = list(self._cases)
        rng.shuffle(shuffled)
        split_idx = int(len(shuffled) * train_ratio)
        return shuffled[:split_idx], shuffled[split_idx:]

    def version(self) -> str:
        """Return the dataset version."""
        return self._version

    def all_cases(self) -> List[EvaluationCase]:
        """Return all loaded cases."""
        if not self._loaded:
            raise RuntimeError("Dataset not loaded. Call load() first.")
        return list(self._cases)

    @property
    def name(self) -> str:
        """Return the dataset name."""
        return self._dataset_name