"""Unit tests for human review queue module."""

import pytest

from neo_mcp.evaluation.review import (
    InMemoryReviewQueue,
    ReviewEntry,
    ReviewQueue,
    ReviewStatus,
)


class TestReviewQueue:
    """Test ReviewQueue ABC cannot be instantiated."""

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ReviewQueue()  # type: ignore


class TestReviewEntry:
    """Test ReviewEntry dataclass."""

    def test_defaults(self):
        entry = ReviewEntry(entry_id="r1", case_id="c1", metric_name="exact_match")
        assert entry.entry_id == "r1"
        assert entry.case_id == "c1"
        assert entry.metric_name == "exact_match"
        assert entry.status == ReviewStatus.PENDING
        assert entry.reviewer_notes == ""


class TestInMemoryReviewQueue:
    """Test InMemoryReviewQueue implementation."""

    def setup_method(self):
        self.queue = InMemoryReviewQueue()

    def test_enqueue_assigns_id_and_timestamp(self):
        entry = ReviewEntry(case_id="c1", metric_name="m1", score=0.5)
        entry_id = self.queue.enqueue(entry)

        assert entry_id.startswith("review_")
        assert entry.created_at != ""

        retrieved = self.queue.get_entry(entry_id)
        assert retrieved is not None
        assert retrieved.entry_id == entry_id

    def test_pending_returns_unresolved_entries(self):
        self.queue.enqueue(ReviewEntry(case_id="c1", metric_name="m1", score=0.5))
        self.queue.enqueue(ReviewEntry(case_id="c2", metric_name="m2", score=0.3))

        assert len(self.queue.pending()) == 2

    def test_resolve_entry(self):
        entry_id = self.queue.enqueue(
            ReviewEntry(case_id="c1", metric_name="m1", score=0.5)
        )

        resolved = self.queue.resolve(
            entry_id, ReviewStatus.APPROVED, "Looks good"
        )
        assert resolved is True

        entry = self.queue.get_entry(entry_id)
        assert entry.status == ReviewStatus.APPROVED
        assert entry.reviewer_notes == "Looks good"
        assert entry.resolved_at != ""

        # No longer pending
        assert len(self.queue.pending()) == 0

    def test_resolve_nonexistent_entry(self):
        resolved = self.queue.resolve(
            "nonexistent", ReviewStatus.APPROVED
        )
        assert resolved is False

    def test_resolve_already_resolved_returns_false(self):
        entry_id = self.queue.enqueue(
            ReviewEntry(case_id="c1", metric_name="m1", score=0.5)
        )
        self.queue.resolve(entry_id, ReviewStatus.APPROVED)

        # Second resolve should fail
        resolved = self.queue.resolve(entry_id, ReviewStatus.REJECTED)
        assert resolved is False

    def test_multiple_status_resolutions(self):
        entry_id = self.queue.enqueue(
            ReviewEntry(case_id="c1", metric_name="m1", score=0.5)
        )

        # Test all resolution statuses
        for status in [ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.REQUESTED_CHANGES]:
            self.queue = InMemoryReviewQueue()
            eid = self.queue.enqueue(ReviewEntry(case_id="c1", metric_name="m1", score=0.5))
            assert self.queue.resolve(eid, status) is True
            entry = self.queue.get_entry(eid)
            assert entry.status == status

    def test_all_entries_returns_both_pending_and_resolved(self):
        e1 = self.queue.enqueue(ReviewEntry(case_id="c1", metric_name="m1", score=0.5))
        e2 = self.queue.enqueue(ReviewEntry(case_id="c2", metric_name="m2", score=0.3))

        self.queue.resolve(e1, ReviewStatus.APPROVED)

        all_entries = self.queue.all_entries()
        assert len(all_entries) == 2

    def test_incrementing_counter(self):
        id1 = self.queue.enqueue(ReviewEntry(case_id="c1", metric_name="m1", score=0.5))
        id2 = self.queue.enqueue(ReviewEntry(case_id="c2", metric_name="m2", score=0.3))

        assert id1 == "review_1"
        assert id2 == "review_2"