"""Unit tests for eval instrumentation module."""

import pytest

from neo_mcp.evaluation.eval_instrumentation import (
    EvalInstrumentation,
    EVAL_FAILURE_PATTERNS,
    EvalEvent,
    extend_failure_classifier,
)
from neo_mcp.observability.instrumentation import ConsoleInstrumentation
from neo_mcp.recovery.failure_classifier import RuleBasedFailureClassifier


class TestEvalEvent:
    """Test EvalEvent dataclass."""

    def test_defaults(self):
        event = EvalEvent(event_type="run_start")
        assert event.event_type == "run_start"
        assert event.case_id == ""
        assert event.metric_name == ""
        assert event.score == 0.0
        assert event.details == {}
        assert event.timestamp == ""


class TestEvalInstrumentation:
    """Test EvalInstrumentation composition with ConsoleInstrumentation."""

    def setup_method(self):
        self.base = ConsoleInstrumentation(verbose=False)
        self.eval_instr = EvalInstrumentation(instrumentation=self.base)

    def test_composition_delegates_to_base(self):
        """EvalInstrumentation composes with ConsoleInstrumentation."""
        assert self.eval_instr.instrumentation is self.base

    def test_record_eval_event_stores_event(self):
        self.eval_instr.record_eval_event(
            event_type="run_start",
            case_id="all",
            metric_name="exact_match",
            score=0.95,
            details={"num_cases": 3},
        )
        events = self.eval_instr.get_eval_events()
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "run_start"
        assert event.case_id == "all"
        assert event.metric_name == "exact_match"
        assert event.score == 0.95
        assert event.details == {"num_cases": 3}
        assert event.timestamp != ""

    def test_record_eval_event_logs_to_instrumentation(self):
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c1")

        # Check that the underlying instrumentation logged it
        metrics = self.eval_instr.get_metrics_snapshot()
        assert "eval.event.case_start" in metrics
        assert metrics["eval.event.case_start"] >= 1

    def test_multiple_events(self):
        self.eval_instr.record_eval_event(event_type="run_start", case_id="all")
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c1")
        self.eval_instr.record_eval_event(event_type="case_complete", case_id="c1", metric_name="exact_match", score=1.0)
        self.eval_instr.record_eval_event(event_type="run_complete", case_id="all")

        assert len(self.eval_instr.get_eval_events()) == 4

    def test_filter_by_event_type(self):
        self.eval_instr.record_eval_event(event_type="run_start")
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c1")
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c2")

        events = self.eval_instr.get_eval_events(event_type="case_start")
        assert len(events) == 2

    def test_filter_by_case_id(self):
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c1")
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c2")

        events = self.eval_instr.get_eval_events(case_id="c1")
        assert len(events) == 1
        assert events[0].case_id == "c1"

    def test_clear_events(self):
        self.eval_instr.record_eval_event(event_type="run_start")
        self.eval_instr.clear()

        assert len(self.eval_instr.get_eval_events()) == 0
        assert self.eval_instr.get_metrics_snapshot() == {}

    def test_get_metrics_snapshot_delegates(self):
        self.eval_instr.record_eval_event(event_type="case_start", case_id="c1")
        snapshot = self.eval_instr.get_metrics_snapshot()
        assert isinstance(snapshot, dict)

    def test_default_construction(self):
        """EvalInstrumentation can be created without an explicit base instrumentation."""
        instr = EvalInstrumentation()
        assert instr.instrumentation is not None
        assert isinstance(instr.instrumentation, ConsoleInstrumentation)

    def test_metric_increment_on_eval_event(self):
        """Metric counter is incremented for each event."""
        self.eval_instr.record_eval_event(event_type="run_start", metric_name="exact_match")
        self.eval_instr.record_eval_event(event_type="case_complete", metric_name="success_rate")

        metrics = self.eval_instr.get_metrics_snapshot()
        assert "eval.metric.exact_match" in metrics
        assert "eval.metric.success_rate" in metrics


class TestEVAL_FAILURE_PATTERNS:
    """Test EVAL_FAILURE_PATTERNS structure."""

    def test_has_patterns(self):
        assert len(EVAL_FAILURE_PATTERNS) > 0

    def test_each_pattern_has_required_fields(self):
        for pattern in EVAL_FAILURE_PATTERNS:
            assert "pattern" in pattern
            assert "category" in pattern
            assert "subtype" in pattern
            assert "description" in pattern

    def test_patterns_use_valid_regex(self):
        import re
        for pattern in EVAL_FAILURE_PATTERNS:
            compiled = re.compile(pattern["pattern"])
            assert compiled is not None

    def test_patterns_can_match(self):
        import re
        test_strings = {
            "error during evaluation": "EVAL_ERROR",
            "timeout": "EVAL_TIMEOUT",
            "empty response": "EVAL_EMPTY_RESPONSE",
            "tool call failed": "EVAL_TOOL_FAILURE",
            "malformed output": "EVAL_MALFORMED_OUTPUT",
            "unexpected exception": "EVAL_UNEXPECTED_ERROR",
            "not found": "EVAL_NOT_FOUND",
            "invalid result": "EVAL_INVALID_RESULT",
        }

        for text, expected_category in test_strings.items():
            found = False
            for pattern in EVAL_FAILURE_PATTERNS:
                if re.search(pattern["pattern"], text):
                    assert pattern["category"] == expected_category, f"Mismatch for '{text}'"
                    found = True
                    break
            assert found, f"No pattern matched '{text}'"


class TestExtendFailureClassifier:
    """Test extend_failure_classifier composition utility."""

    def test_extends_with_eval_patterns(self):
        base = RuleBasedFailureClassifier()
        extended = extend_failure_classifier(base)

        assert isinstance(extended, RuleBasedFailureClassifier)
        assert extended is not base  # New instance

    def test_extends_with_custom_patterns(self):
        base = RuleBasedFailureClassifier()
        custom = [{"pattern": "custom error", "category": "CUSTOM", "subtype": "test", "description": "test"}]
        extended = extend_failure_classifier(base, extra_patterns=custom)

        # Extended classifier should have more patterns
        # Verify by testing classification
        result = extended.classify("custom error happened")
        assert result.category.value == "CUSTOM"