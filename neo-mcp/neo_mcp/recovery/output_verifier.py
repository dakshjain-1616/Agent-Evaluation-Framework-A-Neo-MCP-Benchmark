"""Output verifier — validates tool outputs against expected schemas."""

from __future__ import annotations

from typing import Any, Dict, Optional

from neo_mcp.core.interfaces import OutputVerifier
from neo_mcp.core.models import Step


class PassThroughVerifier(OutputVerifier):
    """Pass-through verifier — accepts any output as valid.

    Useful for testing or when output validation is not needed.
    """

    def verify(
        self,
        output: Any,
        step: Step,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Accept any output."""
        return True


class SchemaOutputVerifier(OutputVerifier):
    """Verifies tool output against a JSON schema.

    Supports basic type checking and required field validation.
    For more complex needs, extend or use a full JSON Schema library.
    """

    def verify(
        self,
        output: Any,
        step: Step,
        output_schema: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Verify output matches the expected schema.

        Args:
            output: The tool output to verify.
            step: The step that produced this output.
            output_schema: A dict describing expected output structure:
                {
                    "type": "object" | "array" | "string" | "number" | "boolean" | "any",
                    "required": ["field1", ...],  # for type "object"
                    "properties": {                 # for type "object"
                        "field1": {"type": "string"},
                        ...
                    },
                    "items": { ... } or "item_type": { ... }  # for type "array"
                }

        Returns:
            True if output matches schema, False otherwise.
        """
        if output_schema is None:
            return True

        return self._validate(output, output_schema)

    def _validate(self, value: Any, schema: Dict[str, Any]) -> bool:
        """Recursively validate a value against a schema."""
        expected_type = schema.get("type", "any")

        if expected_type == "any":
            return True

        if expected_type == "object":
            if not isinstance(value, dict):
                return False

            # Check required fields
            required = schema.get("required", [])
            for field in required:
                if field not in value:
                    return False

            # Check property types
            properties = schema.get("properties", {})
            for field, field_schema in properties.items():
                if field in value:
                    if not self._validate(value[field], field_schema):
                        return False

            return True

        if expected_type == "array":
            if not isinstance(value, list):
                return False
            # Support both "items" (JSON Schema standard) and "item_type" (legacy)
            item_schema = schema.get("items") or schema.get("item_type")
            if item_schema:
                for item in value:
                    if not self._validate(item, item_schema):
                        return False
            return True

        if expected_type == "string":
            if not isinstance(value, str):
                return False
            # Check enum values if present
            enum_values = schema.get("enum")
            if enum_values is not None:
                if value not in enum_values:
                    return False
            return True

        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        if expected_type == "boolean":
            return isinstance(value, bool)

        # Unknown type — pass through
        return True