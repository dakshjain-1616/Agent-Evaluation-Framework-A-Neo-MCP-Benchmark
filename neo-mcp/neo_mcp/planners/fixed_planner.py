"""Fixed planner — returns a predetermined plan.

Used for testing and deterministic demos.
"""

from __future__ import annotations

from typing import Any, Dict, List

from neo_mcp.core.interfaces import Planner
from neo_mcp.core.models import Plan, Step


class FixedPlanner(Planner):
    """Planner that returns a predetermined plan.

    Useful for testing and deterministic demos where the plan is known in advance.
    """

    def __init__(self, plan: Plan) -> None:
        self._plan = plan

    async def plan(
        self, goal: str, tool_descriptions: List[Dict[str, Any]]
    ) -> Plan:
        """Return the predetermined plan regardless of goal/tools."""
        return self._plan

    @classmethod
    def from_steps(
        cls,
        goal: str,
        steps: List[Dict[str, Any]],
    ) -> "FixedPlanner":
        """Create a FixedPlanner from a list of step dicts.

        Each step dict should have: tool_name, arguments, and optionally
        step_id, description, max_retries, timeout_seconds.
        """
        plan_steps = []
        for i, s in enumerate(steps):
            plan_steps.append(
                Step(
                    step_id=s.get("step_id", f"step_{i+1}"),
                    tool_name=s["tool_name"],
                    arguments=s.get("arguments", {}),
                    description=s.get("description"),
                    max_retries=s.get("max_retries", 3),
                    timeout_seconds=s.get("timeout_seconds"),
                )
            )
        return cls(Plan(goal=goal, steps=plan_steps))