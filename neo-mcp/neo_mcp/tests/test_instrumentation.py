"""Unit tests for ConsoleInstrumentation — no real API calls."""

from neo_mcp.observability.instrumentation import ConsoleInstrumentation


class TestConsoleInstrumentation:
    """Test structured logging, metrics, and tracing."""

    def setup_method(self):
        self.instr = ConsoleInstrumentation(verbose=False)

    def test_log_records_message(self):
        self.instr.log("INFO", "test message", component="test")
        logs = self.instr.get_logs()
        assert len(logs) >= 1
        last = logs[-1]
        assert last["level"] == "INFO"
        assert last["message"] == "test message"
        # Context goes in a sub-dict
        assert last["context"]["component"] == "test"

    def test_log_multiple_entries(self):
        self.instr.log("INFO", "first")
        self.instr.log("WARN", "second")
        self.instr.log("ERROR", "third")
        logs = self.instr.get_logs()
        assert len(logs) == 3

    def test_increment_metric(self):
        self.instr.increment("steps_completed")
        self.instr.increment("steps_completed")
        self.instr.increment("errors", tool="weather")
        metrics = self.instr.get_metrics_snapshot()
        assert metrics["steps_completed"] == 2
        # Tagged metrics use key format: name[tag=val]
        assert metrics["errors[tool=weather]"] == 1

    def test_increment_with_tags_in_key(self):
        self.instr.increment("recoveries", strategy="retry")
        self.instr.increment("recoveries", strategy="repair")
        metrics = self.instr.get_metrics_snapshot()
        # Tags create separate keys
        assert "recoveries[strategy=retry]" in metrics
        assert "recoveries[strategy=repair]" in metrics

    def test_record_trace(self):
        self.instr.record_trace("step_1", "execute", 150.0, status="success")
        self.instr.record_trace("step_1", "recover", 200.0, status="recovered")
        traces = self.instr.get_traces()
        assert len(traces) == 2
        assert traces[0]["step_id"] == "step_1"
        assert traces[0]["event"] == "execute"
        assert traces[0]["duration_ms"] == 150.0
        assert traces[0]["attributes"]["status"] == "success"

    def test_clear_resets_all(self):
        self.instr.log("INFO", "msg")
        self.instr.increment("counter")
        self.instr.record_trace("s1", "e", 1.0, status="ok")
        self.instr.clear()
        assert len(self.instr.get_logs()) == 0
        assert self.instr.get_metrics_snapshot() == {}
        assert len(self.instr.get_traces()) == 0

    def test_verbose_logging_does_not_crash(self):
        instr = ConsoleInstrumentation(verbose=True)
        instr.log("INFO", "verbose message")
        instr.increment("verbose_counter")
        instr.record_trace("s1", "e", 1.0, status="ok")
        # Should not raise any exceptions

    def test_increment_non_existent_metric_creates_it(self):
        self.instr.increment("brand_new_metric")
        metrics = self.instr.get_metrics_snapshot()
        assert metrics["brand_new_metric"] == 1

    def test_log_with_additional_context(self):
        self.instr.log("ERROR", "failure", step="step_2", tool="weather",
                       attempt=3, error_msg="timeout")
        logs = self.instr.get_logs()
        last = logs[-1]
        ctx = last["context"]
        assert ctx["step"] == "step_2"
        assert ctx["tool"] == "weather"
        assert ctx["attempt"] == 3
        assert ctx["error_msg"] == "timeout"