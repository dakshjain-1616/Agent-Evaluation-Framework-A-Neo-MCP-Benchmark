"""Unit tests for FixedPlanner and LLMPlanner — no real API calls."""

import pytest

from neo_mcp.core.models import Plan, Step
from neo_mcp.planners.fixed_planner import FixedPlanner


class TestFixedPlanner:
    """FixedPlanner should deterministically return predefined steps."""

    def test_from_steps_creates_plan(self):
        steps = [
            {"step_id": "1", "tool_name": "tool_a", "arguments": {"x": 1}, "description": "Step A"},
            {"step_id": "2", "tool_name": "tool_b", "arguments": {"y": 2}, "description": "Step B"},
        ]
        planner = FixedPlanner.from_steps("Test goal", steps)
        assert len(planner._plan.steps) == 2
        assert planner._plan.goal == "Test goal"

    @pytest.mark.asyncio
    async def test_plan_returns_same_steps(self):
        steps = [
            {"step_id": "s1", "tool_name": "ping", "arguments": {}, "description": "Ping"},
            {"step_id": "s2", "tool_name": "echo", "arguments": {"msg": "hi"}, "description": "Echo"},
        ]
        planner = FixedPlanner.from_steps("Goal", steps)
        plan = await planner.plan("Goal", {})
        assert isinstance(plan, Plan)
        assert len(plan.steps) == 2
        for original, returned in zip(steps, plan.steps):
            assert returned.step_id == original["step_id"]
            assert returned.tool_name == original["tool_name"]
            assert returned.arguments == original.get("arguments", {})
            assert returned.description == original.get("description", "")

    @pytest.mark.asyncio
    async def test_plan_ignores_tool_descriptions(self):
        steps = [{"step_id": "1", "tool_name": "t", "arguments": {}, "description": ""}]
        planner = FixedPlanner.from_steps("Goal", steps)
        plan = await planner.plan("Different goal", {"some_tool": "description"})
        assert len(plan.steps) == 1
        assert plan.goal == "Goal"  # Uses the stored goal

    @pytest.mark.asyncio
    async def test_plan_deterministic(self):
        steps = [{"step_id": "1", "tool_name": "t", "arguments": {}, "description": ""}]
        planner = FixedPlanner.from_steps("Goal", steps)
        plan1 = await planner.plan("Goal", {})
        plan2 = await planner.plan("Goal", {})
        assert len(plan1.steps) == len(plan2.steps)
        assert plan1.steps[0].tool_name == plan2.steps[0].tool_name


class TestLLMPlanner:
    """Test LLMPlanner with FakeLLMProvider — no real API calls."""

    @pytest.mark.asyncio
    async def test_plan_returns_plan_with_valid_json(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.planners.llm_planner import LLMPlanner

        fake = FakeLLMProvider(default_response='{"goal": "Test goal", "steps": [{"step_id": "1", "tool_name": "ping", "arguments": {}, "description": "Ping step"}]}')
        planner = LLMPlanner(llm_provider=fake, model_id="claude-opus-4-8")
        plan = await planner.plan("Test goal", [{"name": "ping", "description": "Returns pong"}])
        assert isinstance(plan, Plan)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool_name == "ping"

    @pytest.mark.asyncio
    async def test_plan_falls_back_on_invalid_json(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.planners.llm_planner import LLMPlanner

        fake = FakeLLMProvider(default_response="this is not json")
        planner = LLMPlanner(llm_provider=fake, model_id="claude-opus-4-8")
        with pytest.raises(ValueError):
            await planner.plan("Test goal", [])

    @pytest.mark.asyncio
    async def test_plan_falls_back_on_missing_steps(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.planners.llm_planner import LLMPlanner

        fake = FakeLLMProvider(default_response='{"goal": "test"}')
        planner = LLMPlanner(llm_provider=fake, model_id="claude-opus-4-8")
        with pytest.raises(ValueError):
            await planner.plan("test", [])

    @pytest.mark.asyncio
    async def test_plan_parses_multiple_steps(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.planners.llm_planner import LLMPlanner

        json_response = '''{"goal": "Multi-step", "steps": [
            {"step_id": "1", "tool_name": "get_weather", "arguments": {"city": "London"}, "description": "Get weather"},
            {"step_id": "2", "tool_name": "send_email", "arguments": {"to": "a@b.com"}, "description": "Send email"}
        ]}'''
        fake = FakeLLMProvider(default_response=json_response)
        planner = LLMPlanner(llm_provider=fake, model_id="claude-opus-4-8")
        plan = await planner.plan("Multi-step", [])
        assert len(plan.steps) == 2
        assert plan.steps[0].tool_name == "get_weather"
        assert plan.steps[1].tool_name == "send_email"

    @pytest.mark.asyncio
    async def test_plan_empty_json_response_falls_back(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.planners.llm_planner import LLMPlanner

        fake = FakeLLMProvider(default_response="")
        planner = LLMPlanner(llm_provider=fake, model_id="claude-opus-4-8")
        with pytest.raises(ValueError):
            await planner.plan("test", [])