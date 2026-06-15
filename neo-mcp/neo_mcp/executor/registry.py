"""Tool registry — manages tool definitions and dispatch."""

from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neo_mcp.core.models import Step, StepResult, Verdict


class ToolRegistry:
    """Registry for tool definitions.

    Tools are registered with name, function, input_schema, and output_schema.
    Schemas are used for argument repair and output verification.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        description: str = "",
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name.
            func: The function to call (sync or async).
            input_schema: Optional JSON schema for input validation.
            output_schema: Optional JSON schema for output validation.
            description: Human-readable description of what the tool does.
        """
        # Allow re-registration (last registration wins, keeps tests simple)
        self._tools[name] = {
            "name": name,
            "func": func,
            "input_schema": input_schema or {},
            "output_schema": output_schema or {},
            "description": description,
        }

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all registered tool definitions."""
        return list(self._tools.values())

    def get_descriptions(self) -> List[Dict[str, Any]]:
        """Get tool descriptions suitable for planner context."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
                "output_schema": t["output_schema"],
            }
            for t in self._tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def remove(self, name: str) -> None:
        """Remove a registered tool."""
        self._tools.pop(name, None)

    def clear(self) -> None:
        """Remove all registered tools."""
        self._tools.clear()


class ToolExecutor:
    """Executes steps by dispatching to registered tools.

    Handles both sync and async functions, wraps exceptions into StepResults.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute_step(self, step: Step) -> StepResult:
        """Execute a single step by dispatching to the registered tool.

        Args:
            step: The step to execute (contains tool_name and arguments).

        Returns:
            StepResult with success/failure, output/error, and duration.
        """
        tool_def = self._registry.get(step.tool_name)
        if tool_def is None:
            return StepResult(
                step=step,
                success=False,
                error=f"Unknown tool: '{step.tool_name}'",
                exception_type="ValueError",
                duration_ms=0.0,
                attempts=1,
                verdict=Verdict.FAILURE,
            )

        func = tool_def["func"]
        start = time.monotonic()

        try:
            # Call the function
            if inspect.iscoroutinefunction(func):
                output = await func(**step.arguments)
            else:
                output = func(**step.arguments)

            duration = (time.monotonic() - start) * 1000

            return StepResult(
                step=step,
                success=True,
                output=output,
                duration_ms=round(duration, 2),
                attempts=1,
                verdict=Verdict.SUCCESS,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000

            return StepResult(
                step=step,
                success=False,
                error=str(e),
                exception_type=f"{type(e).__module__}.{type(e).__qualname__}",
                duration_ms=round(duration, 2),
                attempts=1,
                verdict=Verdict.FAILURE,
            )