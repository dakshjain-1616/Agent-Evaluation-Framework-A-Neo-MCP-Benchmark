"""Demo tools with controlled flakiness for the E2E demo.

Each tool simulates specific failure modes to exercise the recovery pipeline.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict


# --- Stateful counters for flaky tools ---
_weather_call_count: int = 0
_database_call_count: int = 0
_report_call_count: int = 0
_calculate_call_count: int = 0


def _reset_state() -> None:
    """Reset all tool state counters (for testing)."""
    global _weather_call_count, _database_call_count, _report_call_count, _calculate_call_count
    _weather_call_count = 0
    _database_call_count = 0
    _report_call_count = 0
    _calculate_call_count = 0


def get_weather(city: str) -> str:
    """Get weather for a city. Fails with rate limit every 3rd call.

    Args:
        city: City name.

    Returns:
        Weather report string.

    Raises:
        RuntimeError: Rate limit error on every 3rd call.
    """
    global _weather_call_count
    _weather_call_count += 1

    # Fail every 3rd call with rate limit
    if _weather_call_count % 3 == 0:
        raise RuntimeError("429 Too Many Requests: Rate limit exceeded for weather API")

    time.sleep(0.05)  # Simulate small latency
    temperatures = {"london": 15, "paris": 18, "tokyo": 22, "new york": 20, "sydney": 25}
    temp = temperatures.get(city.lower(), random.randint(5, 35))
    return f"Weather in {city}: {temp}°C, partly cloudy"


def query_database(query: str) -> Any:
    """Query a simulated database.

    - 40% of calls pass schema-violating queries (e.g. missing required fields)
    - 50% of valid calls return malformed data

    Args:
        query: The query string.

    Returns:
        Query results (dict or list).

    Raises:
        ValueError: Schema violation on 40% of calls.
    """
    global _database_call_count
    _database_call_count += 1

    # 40% chance: schema-violating query → triggers argument repair
    rand = random.random()
    if rand < 0.4:
        raise ValueError(
            "Schema violation: query missing required field 'table' or 'columns'. "
            "Expected format: SELECT columns FROM table WHERE condition"
        )

    # Simulate valid queries
    time.sleep(0.03)

    # 50% of valid calls return malformed data (output verification will catch)
    if random.random() < 0.5:
        # Return data that passes as valid but may be malformed (for demo purposes)
        # The output schema will catch missing fields
        return {"status": "ok", "rows": [{"id": 1, "name": "Item 1"}], "total": 1}

    return {
        "status": "ok",
        "columns": ["id", "name", "price"],
        "rows": [
            {"id": 1, "name": "Widget", "price": 10.99},
            {"id": 2, "name": "Gadget", "price": 24.99},
        ],
        "total": 2,
    }


def validate_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a report. First call fails output verification every time.

    This exercises the 'output-verification-fails-then-recovers' path.
    The tool itself succeeds (no exception), but the first call returns
    a dict missing the 'status' field, causing SchemaOutputVerifier to
    flag it as invalid — which triggers a retry. Subsequent calls
    return valid output (output verification passes).

    Args:
        data: Report data dict with 'report_type' field.

    Returns:
        Dict with report results (first call lacks 'status', retries succeed).
    """
    global _report_call_count
    _report_call_count += 1

    time.sleep(0.02)

    report_type = data.get("report_type", "unknown")

    # First call always fails output verification (missing 'status')
    if _report_call_count == 1:
        return {
            "message": f"Report '{report_type}' processed, awaiting confirmation",
        }

    # Subsequent calls return valid output
    return {
        "status": "complete",
        "message": f"Report '{report_type}' processed successfully",
        "summary": "All checks passed",
    }


def calculate(expression: str) -> float:
    """Evaluate a mathematical expression. Random timeout 30% of calls.

    Args:
        expression: Math expression string.

    Returns:
        Numeric result.

    Raises:
        RuntimeError: Timeout on 30% of calls.
    """
    global _calculate_call_count
    _calculate_call_count += 1

    # 30% chance: transient timeout
    if random.random() < 0.3:
        raise TimeoutError(f"Calculation timed out for expression: '{expression}'")

    time.sleep(0.02)
    # Simple safe eval for demo purposes
    safe_expr = expression.replace(" ", "")
    allowed = set("0123456789+-*/().")
    if not all(c in allowed for c in safe_expr):
        raise ValueError(f"Invalid characters in expression: '{expression}'")

    result = eval(safe_expr, {"__builtins__": {}}, {})
    return float(result)


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. Always succeeds (control tool).

    Args:
        to: Recipient email.
        subject: Email subject.
        body: Email body.

    Returns:
        Confirmation message.
    """
    time.sleep(0.01)
    return f"Email sent to {to} with subject '{subject}'"


# Input schemas for the tools (used for argument repair)
TOOL_INPUT_SCHEMAS = {
    "get_weather": {
        "type": "object",
        "required": ["city"],
        "properties": {
            "city": {"type": "string", "description": "City name"}
        },
    },
    "query_database": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "SQL query string"}
        },
    },
    "validate_report": {
        "type": "object",
        "required": ["data"],
        "properties": {
            "data": {
                "type": "object",
                "required": ["report_type"],
                "properties": {
                    "report_type": {"type": "string"}
                },
            }
        },
    },
    "calculate": {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {"type": "string", "description": "Math expression"}
        },
    },
    "send_email": {
        "type": "object",
        "required": ["to", "subject", "body"],
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
    },
}

# Output schemas for the tools (used for output verification)
# String and number returns use type "any" since they have no structure to validate.
# Object returns use detailed schemas for meaningful verification.
TOOL_OUTPUT_SCHEMAS = {
    "get_weather": {
        "type": "any",
    },
    "query_database": {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string"},
            "columns": {"type": "array"},
            "rows": {"type": "array"},
            "total": {"type": "number"},
        },
    },
    "validate_report": {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"type": "string"},
            "message": {"type": "string"},
        },
    },
    "calculate": {
        "type": "any",
    },
    "send_email": {
        "type": "any",
    },
}