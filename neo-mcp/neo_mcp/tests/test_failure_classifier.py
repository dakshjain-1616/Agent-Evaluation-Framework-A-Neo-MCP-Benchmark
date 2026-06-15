"""Unit tests for RuleBasedFailureClassifier — no real API calls."""

from neo_mcp.core.models import FailureCategory, RecoveryAction
from neo_mcp.recovery.failure_classifier import RuleBasedFailureClassifier


class TestRuleBasedFailureClassifier:
    """Test all pattern-matching rules in the classifier."""

    def setup_method(self):
        self.classifier = RuleBasedFailureClassifier()

    def _classify(self, msg: str, exc_type: str = None):
        return self.classifier.classify(msg, exc_type)

    # --- TRANSIENT: rate limits ---

    def test_429_rate_limit(self):
        c = self._classify("429 Too Many Requests")
        assert c.category == FailureCategory.TRANSIENT
        assert c.action == RecoveryAction.RETRY
        assert c.is_transient is True

    def test_rate_limit_text(self):
        c = self._classify("rate limit exceeded for API")
        assert c.category == FailureCategory.TRANSIENT

    def test_too_many_requests_text(self):
        c = self._classify("Too many requests, slow down")
        assert c.category == FailureCategory.TRANSIENT

    # --- TRANSIENT: timeouts ---

    def test_timeout_message(self):
        c = self._classify("Request timed out after 30s")
        assert c.category == FailureCategory.TRANSIENT
        assert c.action == RecoveryAction.RETRY
        assert c.is_transient is True

    def test_timeout_exception(self):
        c = self._classify("operation failed", "TimeoutError")
        assert c.category == FailureCategory.TRANSIENT

    # --- TRANSIENT: connection errors ---

    def test_connection_error_exception(self):
        c = self._classify("could not connect", "ConnectionError")
        assert c.category == FailureCategory.TRANSIENT
        assert c.is_transient is True

    def test_connection_refused_text(self):
        c = self._classify("Connection refused by server")
        assert c.category == FailureCategory.TRANSIENT

    # --- PERMANENT_AUTH ---

    def test_401_unauthorized(self):
        c = self._classify("401 Unauthorized")
        assert c.category == FailureCategory.PERMANENT_AUTH
        assert c.action == RecoveryAction.FAIL
        assert c.is_transient is False

    def test_403_forbidden(self):
        c = self._classify("403 Forbidden: access denied")
        assert c.category == FailureCategory.PERMANENT_AUTH

    def test_invalid_api_key(self):
        c = self._classify("Invalid API key provided")
        assert c.category == FailureCategory.PERMANENT_AUTH

    def test_authentication_failed(self):
        c = self._classify("Authentication failed - bad token")
        assert c.category == FailureCategory.PERMANENT_AUTH

    # --- PERMANENT_BAD_ARGS ---

    def test_key_error(self):
        c = self._classify("key 'missing_field' not found", "KeyError")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS
        assert c.action == RecoveryAction.REPAIR_AND_RETRY
        assert c.requires_repair is True

    def test_type_error(self):
        c = self._classify("expected string but got int", "TypeError")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS

    def test_value_error(self):
        c = self._classify("invalid value for parameter", "ValueError")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS

    def test_validation_error_text(self):
        c = self._classify("ValidationError: schema mismatch")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS

    def test_schema_violation(self):
        c = self._classify("Schema violation: missing required field")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS

    def test_missing_required(self):
        c = self._classify("missing required argument 'table'")
        assert c.category == FailureCategory.PERMANENT_BAD_ARGS

    # --- TRANSIENT: output verification failure ---

    def test_output_verification_failure(self):
        c = self._classify("Output verification failed for tool 'validate_report'")
        assert c.category == FailureCategory.TRANSIENT
        assert c.action == RecoveryAction.RETRY
        assert c.is_transient is True

    def test_output_verification_error_exception(self):
        c = self._classify("output did not match expected schema", "OutputVerificationError")
        assert c.category == FailureCategory.TRANSIENT

    # --- PERMANENT_DOWNSTREAM ---

    def test_500_internal_server_error(self):
        c = self._classify("500 Internal Server Error")
        assert c.category == FailureCategory.PERMANENT_DOWNSTREAM
        assert c.action == RecoveryAction.ESCALATE

    def test_503_service_unavailable(self):
        c = self._classify("503 Service Unavailable")
        assert c.category == FailureCategory.PERMANENT_DOWNSTREAM

    def test_service_unavailable_text(self):
        c = self._classify("service unavailable")
        assert c.category == FailureCategory.PERMANENT_DOWNSTREAM

    # --- UNKNOWN ---

    def test_unknown_error(self):
        c = self._classify("Some random error occurred")
        assert c.category == FailureCategory.UNKNOWN
        assert c.action == RecoveryAction.FAIL
        assert c.is_transient is False

    def test_empty_message(self):
        c = self._classify("")
        assert c.category == FailureCategory.UNKNOWN

    def test_none_message(self):
        c = self._classify(None)
        assert c.category == FailureCategory.UNKNOWN

    def test_none_exception_and_message(self):
        c = self._classify(None, None)
        assert c.category == FailureCategory.UNKNOWN