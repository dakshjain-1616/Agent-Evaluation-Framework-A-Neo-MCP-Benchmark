"""LLM-powered planner — uses an LLM to generate a plan from a goal.

Uses the LLMProvider interface, so it works with any provider.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from neo_mcp.core.interfaces import LLMProvider, Planner
from neo_mcp.core.models import Plan, Step


class LLMPlanner(Planner):
    """Planner that uses an LLM to generate a multi-step plan from a goal.

    The LLM receives the goal and a list of available tool descriptions,
    and returns a structured JSON plan with ordered steps.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        model_id: str = "claude-opus-4-8",
    ) -> None:
        self._llm = llm_provider
        self._model_id = model_id

    async def plan(
        self,
        goal: str,
        tool_descriptions: List[Dict[str, Any]],
    ) -> Plan:
        """Generate a plan to achieve the given goal using the LLM.

        Args:
            goal: The objective the agent should accomplish.
            tool_descriptions: List of available tool metadata dicts.

        Returns:
            A Plan with ordered steps.

        Raises:
            PlanningError: If the LLM fails to produce a valid plan.
        """
        system_prompt = (
            "You are an expert planner that generates step-by-step plans "
            "to achieve goals using available tools. "
            "You MUST output ONLY valid JSON — no markdown, no explanation, "
            "no surrounding text. "
            "The JSON must be an object with the key 'steps' containing an array "
            "of step objects. "
            "Each step object must have: 'tool_name' (string, matching a tool name exactly), "
            "'arguments' (object with parameter names and values), and optionally "
            "'description' (string explaining what this step does)."
        )

        tools_json = json.dumps(tool_descriptions, indent=2)

        user_prompt = (
            f"Goal: {goal}\n\n"
            f"Available tools:\n{tools_json}\n\n"
            "Generate a plan as a JSON object with the key 'steps' containing "
            "an array of step objects. Each step must specify:\n"
            "- 'tool_name': the exact tool name\n"
            "- 'arguments': the arguments to pass\n"
            "- 'description': what this step does\n"
            "Return ONLY the JSON object."
        )

        response = await self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=2048,
            temperature=0.2,
        )

        # Parse the response
        response = response.strip()

        # Strip markdown code fences if present
        if response.startswith("```"):
            start = response.find("{")
            if start >= 0:
                response = response[start:]
            end = response.rfind("}")
            if end >= 0:
                response = response[: end + 1]

        try:
            plan_data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LLM returned invalid JSON for planning: {e}\nRaw: {response[:500]}"
            )

        if "steps" not in plan_data or not isinstance(plan_data["steps"], list):
            raise ValueError(
                f"LLM plan missing 'steps' array. Got keys: {list(plan_data.keys())}"
            )

        steps = []
        for i, step_data in enumerate(plan_data["steps"]):
            if "tool_name" not in step_data:
                raise ValueError(
                    f"Step {i} missing 'tool_name'. Got: {list(step_data.keys())}"
                )

            steps.append(
                Step(
                    step_id=step_data.get("step_id", f"llm_step_{i+1}"),
                    tool_name=step_data["tool_name"],
                    arguments=step_data.get("arguments", {}),
                    description=step_data.get("description"),
                    max_retries=step_data.get("max_retries", 3),
                )
            )

        return Plan(goal=goal, steps=steps)