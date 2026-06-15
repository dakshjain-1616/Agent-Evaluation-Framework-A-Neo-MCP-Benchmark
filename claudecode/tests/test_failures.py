from __future__ import annotations

import pytest

from selfheal import (
    FailureClass,
    HeuristicClassifier,
    InvalidArgumentError,
    PermissionDeniedError,
    RateLimitError,
)


@pytest.fixture
def classifier() -> HeuristicClassifier:
    return HeuristicClassifier()


def test_typed_error_wins_with_full_confidence(classifier):
    f = classifier.classify(RateLimitError("slow down"), tool="t", attempt=1)
    assert f.failure_class is FailureClass.RATE_LIMITED
    assert f.confidence == 1.0
    assert f.transient is True


def test_stdlib_type_mapping(classifier):
    f = classifier.classify(TimeoutError("nope"), tool="t", attempt=2)
    assert f.failure_class is FailureClass.TRANSIENT
    assert f.attempt == 2


@pytest.mark.parametrize(
    "message,expected",
    [
        ("HTTP 429 received", FailureClass.RATE_LIMITED),
        ("403 Forbidden: access denied", FailureClass.PERMISSION),
        ("resource not found", FailureClass.NOT_FOUND),
        ("quota exceeded for project", FailureClass.RESOURCE_EXHAUSTED),
        ("invalid argument: expected int", FailureClass.INVALID_ARGUMENT),
        ("503 service unavailable", FailureClass.UNAVAILABLE),
        ("operation timed out", FailureClass.TRANSIENT),
    ],
)
def test_message_heuristics(classifier, message, expected):
    f = classifier.classify(Exception(message), tool="t", attempt=1)
    assert f.failure_class is expected
    assert 0.0 < f.confidence < 1.0


def test_unknown_when_nothing_matches(classifier):
    f = classifier.classify(Exception("???"), tool="t", attempt=1)
    assert f.failure_class is FailureClass.UNKNOWN
    assert f.confidence < 0.5


def test_class_dispositions():
    assert FailureClass.PERMISSION.terminal
    assert FailureClass.LOGIC.terminal
    assert FailureClass.RATE_LIMITED.needs_backoff
    assert FailureClass.INVALID_ARGUMENT.repairable
    assert FailureClass.BAD_OUTPUT.repairable
    assert not FailureClass.TRANSIENT.needs_backoff
    assert PermissionDeniedError().failure_class is FailureClass.PERMISSION
    assert InvalidArgumentError().failure_class is FailureClass.INVALID_ARGUMENT
