"""Argument repairer — fixes malformed tool arguments for retry."""

from __future__ import annotations

from typing import Any, Dict, Optional

from neo_mcp.core.interfaces import ArgumentRepairer, LLMProvider


class NullArgumentRepairer(ArgumentRepairer):
    """No-op argument repairer — returns original arguments unchanged.

    Useful for testing or when argument repair is not needed.
    """

    async def repair_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_message: str,
        tool_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return arguments unchanged."""
        return arguments


class LLMArgumentRepairer(ArgumentRepairer):
    """Uses an LLMProvider to repair malformed arguments.

    The LLM receives the original arguments, error message, and tool schema,
    and returns a corrected arguments dict.
    """

    def __init__(self, llm_provider: LLMProvider, model_id: str = "claude-opus-4-8") -> None:
        self._llm = llm_provider
        self._model_id = model_id

    async def repair_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        error_message: str,
        tool_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Use LLM to analyze the error and produce corrected arguments."""
        schema_str = ""
        if tool_schema:
            import json
            schema_str = f"\nExpected schema:\n```json\n{json.dumps(tool_schema, indent=2)}\n```"

        system_prompt = (
            "You are an expert at debugging and repairing tool call arguments. "
            "Given the original arguments, error message, and expected schema, "
            "return ONLY corrected arguments as a valid JSON object. "
            "Do not include any explanation, markdown formatting, or surrounding text."
        )

        import json
        user_prompt = (
            f"Tool: {tool_name}\n"
            f"Original arguments: {json.dumps(arguments, indent=2)}\n"
            f"Error: {error_message}"
            f"{schema_str}\n\n"
            "Return ONLY the corrected arguments as a JSON object."
        )

        response = await self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1024,
            temperature=0.0,
        )

        # Parse the response as JSON
        response = response.strip()
        # Strip markdown code fences if present
        if response.startswith("```"):
            # Find the first { or [
            start = response.find("{")
            if start == -1:
                start = response.find("[")
            if start >= 0:
                response = response[start:]
            end = response.rfind("}")
            if end == -1:
                end = response.rfind("]")
            if end >= 0:
                response = response[: end + 1]

        try:
            repaired = json.loads(response)
            if isinstance(repaired, dict):
                return repaired
        except json.JSONDecodeError:
            pass

        # Fallback: return original arguments if parsing fails
        return arguments