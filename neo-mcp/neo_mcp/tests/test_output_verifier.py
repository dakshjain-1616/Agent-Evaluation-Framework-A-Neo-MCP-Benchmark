"""Unit tests for OutputVerifier implementations — no real API calls."""

import pytest

from neo_mcp.core.models import Step
from neo_mcp.recovery.output_verifier import PassThroughVerifier, SchemaOutputVerifier


class TestPassThroughVerifier:
    """PassThroughVerifier always returns True."""

    def setup_method(self):
        self.verifier = PassThroughVerifier()
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={},
            description="Test step",
        )

    def test_always_returns_true_for_any_output(self):
        assert self.verifier.verify(None, self.step) is True

    def test_returns_true_for_empty_dict(self):
        assert self.verifier.verify({}, self.step) is True

    def test_returns_true_for_complex_output(self):
        assert self.verifier.verify({"a": [1, 2, 3]}, self.step) is True

    def test_returns_true_regardless_of_schema(self):
        assert self.verifier.verify("any value", self.step, {"type": "object"}) is True


class TestSchemaOutputVerifier:
    """SchemaOutputVerifier validates output against schema."""

    def setup_method(self):
        self.verifier = SchemaOutputVerifier()
        self.step = Step(
            step_id="test_1",
            tool_name="test_tool",
            arguments={},
            description="Test step",
        )

    # --- object type ---

    def test_valid_object_with_required_fields(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["status", "value"],
        }
        output = {"status": "ok", "value": 42}
        assert self.verifier.verify(output, self.step, schema) is True

    def test_object_missing_required_field(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["status", "value"],
        }
        output = {"status": "ok"}  # missing 'value'
        assert self.verifier.verify(output, self.step, schema) is False

    def test_object_wrong_type_for_field(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["status"],
        }
        output = {"status": "ok", "value": "not_a_number"}
        assert self.verifier.verify(output, self.step, schema) is False

    def test_object_extra_fields_are_ok(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
            },
            "required": ["status"],
        }
        output = {"status": "ok", "extra": "field"}
        assert self.verifier.verify(output, self.step, schema) is True

    def test_object_none_output_fails(self):
        schema = {"type": "object", "required": ["status"]}
        assert self.verifier.verify(None, self.step, schema) is False

    def test_object_output_type_mismatch(self):
        schema = {"type": "object", "required": ["status"]}
        assert self.verifier.verify("string_not_object", self.step, schema) is False

    # --- array type ---

    def test_valid_array(self):
        schema = {"type": "array", "items": {"type": "string"}}
        output = ["a", "b", "c"]
        assert self.verifier.verify(output, self.step, schema) is True

    def test_array_wrong_item_type(self):
        schema = {"type": "array", "items": {"type": "string"}}
        output = ["a", 42, "c"]
        assert self.verifier.verify(output, self.step, schema) is False

    def test_array_empty_is_valid(self):
        schema = {"type": "array", "items": {"type": "string"}}
        assert self.verifier.verify([], self.step, schema) is True

    def test_array_non_list_output_fails(self):
        schema = {"type": "array", "items": {"type": "string"}}
        assert self.verifier.verify({"key": "value"}, self.step, schema) is False

    # --- string type ---

    def test_valid_string(self):
        schema = {"type": "string"}
        assert self.verifier.verify("hello", self.step, schema) is True

    def test_invalid_string_type(self):
        schema = {"type": "string"}
        assert self.verifier.verify(42, self.step, schema) is False

    # --- number type ---

    def test_valid_number_int(self):
        schema = {"type": "number"}
        assert self.verifier.verify(42, self.step, schema) is True

    def test_valid_number_float(self):
        schema = {"type": "number"}
        assert self.verifier.verify(3.14, self.step, schema) is True

    def test_invalid_number_type(self):
        schema = {"type": "number"}
        assert self.verifier.verify("42", self.step, schema) is False

    # --- boolean type ---

    def test_valid_boolean_true(self):
        schema = {"type": "boolean"}
        assert self.verifier.verify(True, self.step, schema) is True

    def test_valid_boolean_false(self):
        schema = {"type": "boolean"}
        assert self.verifier.verify(False, self.step, schema) is True

    def test_invalid_boolean(self):
        schema = {"type": "boolean"}
        assert self.verifier.verify("true", self.step, schema) is False

    # --- edge cases ---

    def test_schema_is_none_passes(self):
        assert self.verifier.verify({"anything"}, self.step, None) is True

    def test_schema_type_any_passes(self):
        assert self.verifier.verify("anything", self.step, {"type": "any"}) is True

    def test_unknown_schema_type(self):
        assert self.verifier.verify("anything", self.step, {"type": "unknown_type"}) is True

    def test_enum_validation_matches(self):
        schema = {"type": "string", "enum": ["metric", "imperial"]}
        assert self.verifier.verify("metric", self.step, schema) is True
        assert self.verifier.verify("imperial", self.step, schema) is True

    def test_enum_validation_no_match(self):
        schema = {"type": "string", "enum": ["metric", "imperial"]}
        assert self.verifier.verify("kelvin", self.step, schema) is False