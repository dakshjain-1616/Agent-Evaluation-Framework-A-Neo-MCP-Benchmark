"""Human review queue for evaluation results.

Provides a mechanism to enqueue evaluation results requiring human review,
track pending reviews, and resolve them. Useful for flagging regressions or
low-scoring cases for manual inspection.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class ReviewStatus(Enum):
    """Status of a review entry."""

    PENDING = auto()
    APPROVED = auto()
    REJECTED = auto()
    REQUESTED_CHANGES = auto()


@dataclass
class ReviewEntry:
    """An item requiring human review.

    Attributes:
        entry_id: Unique identifier for this review entry.
        case_id: The evaluation case identifier.
        metric_name: The metric that triggered this review.
        score: The score that triggered review.
        details: Additional information (error details, results, etc.).
        status: Current review status.
        reviewer_notes: Notes from the human reviewer.
        created_at: ISO timestamp when the entry was created.
        resolved_at: ISO timestamp when the entry was resolved.
    """

    entry_id: str = ""
    case_id: str = ""
    metric_name: str = ""
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer_notes: str = ""
    created_at: str = ""
    resolved_at: str = ""


class ReviewQueue(abc.ABC):
    """Abstract interface for managing review queues."""

    @abc.abstractmethod
    def enqueue(self, entry: ReviewEntry) -> str:
        """Add a review entry to the queue.

        Args:
            entry: The review entry to enqueue.

        Returns:
            The entry_id assigned to this review entry.
        """
        ...

    @abc.abstractmethod
    def pending(self) -> List[ReviewEntry]:
        """Get all pending review entries (not yet resolved).

        Returns:
            List of pending ReviewEntry objects.
        """
        ...

    @abc.abstractmethod
    def resolve(
        self,
        entry_id: str,
        status: ReviewStatus,
        reviewer_notes: str = "",
    ) -> bool:
        """Resolve a pending review entry.

        Args:
            entry_id: The ID of the entry to resolve.
            status: The resolution status (APPROVED, REJECTED, REQUESTED_CHANGES).
            reviewer_notes: Optional notes from the reviewer.

        Returns:
            True if resolved successfully, False if entry not found.
        """
        ...

    @abc.abstractmethod
    def get_entry(self, entry_id: str) -> Optional[ReviewEntry]:
        """Get a review entry by its ID.

        Args:
            entry_id: The entry ID to look up.

        Returns:
            ReviewEntry if found, None otherwise.
        """
        ...

    @abc.abstractmethod
    def all_entries(self) -> List[ReviewEntry]:
        """Get all review entries (pending and resolved).

        Returns:
            List of all ReviewEntry objects.
        """
        ...


class InMemoryReviewQueue(ReviewQueue):
    """In-memory implementation of ReviewQueue.

    Stores all entries in a dict. Not persisted — for testing and demo use.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, ReviewEntry] = {}
        self._counter: int = 0

    def enqueue(self, entry: ReviewEntry) -> str:
        """Add a review entry with auto-generated entry_id and timestamp."""
        self._counter += 1
        entry.entry_id = f"review_{self._counter}"
        entry.created_at = datetime.now(timezone.utc).isoformat()
        entry.status = ReviewStatus.PENDING
        self._entries[entry.entry_id] = entry
        return entry.entry_id

    def pending(self) -> List[ReviewEntry]:
        """Return all pending (unresolved) entries."""
        return [
            e for e in self._entries.values() if e.status == ReviewStatus.PENDING
        ]

    def resolve(
        self,
        entry_id: str,
        status: ReviewStatus,
        reviewer_notes: str = "",
    ) -> bool:
        """Resolve a review entry."""
        if entry_id not in self._entries:
            return False
        entry = self._entries[entry_id]
        if entry.status != ReviewStatus.PENDING:
            return False
        entry.status = status
        entry.reviewer_notes = reviewer_notes
        entry.resolved_at = datetime.now(timezone.utc).isoformat()
        return True

    def get_entry(self, entry_id: str) -> Optional[ReviewEntry]:
        """Get a review entry by ID."""
        return self._entries.get(entry_id)

    def all_entries(self) -> List[ReviewEntry]:
        """Get all entries."""
        return list(self._entries.values())