"""Unit tests for ArgumentRepairer implementations — no real API calls."""

import pytest

from neo_mcp.recovery.argument_repairer import NullArgumentRepairer


class TestNullArgumentRepairer:
    """NullArgumentRepairer should return args unchanged."""

    def setup_method(self):
        self.repairer = NullArgumentRepairer()

    @pytest.mark.asyncio
    async def test_returns_args_unchanged(self):
        args = {"city": "London", "units": "metric"}
        result = await self.repairer.repair_arguments("get_weather", args, "some error")
        assert result == args

    @pytest.mark.asyncio
    async def test_returns_empty_dict_unchanged(self):
        args = {}
        result = await self.repairer.repair_arguments("test_tool", args, "error")
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_none_args(self):
        args = {"key": None}
        result = await self.repairer.repair_arguments("test", args, "err")
        assert result == {"key": None}


class TestLLMArgumentRepairer:
    """Test LLMArgumentRepairer with fake LLM provider."""

    @pytest.mark.asyncio
    async def test_repair_with_valid_json_response(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.recovery.argument_repairer import LLMArgumentRepairer

        fake = FakeLLMProvider(default_response='{"city": "Paris", "units": "metric"}')
        repairer = LLMArgumentRepairer(llm_provider=fake, model_id="claude-opus-4-8")

        args = {"city": "London", "units": "imperial"}
        result = await repairer.repair_arguments(
            "get_weather",
            args,
            "Schema violation: 'units' must be 'metric'",
        )
        assert result == {"city": "Paris", "units": "metric"}

    @pytest.mark.asyncio
    async def test_repair_on_invalid_json_falls_back_to_original_args(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.recovery.argument_repairer import LLMArgumentRepairer

        fake = FakeLLMProvider(default_response="not valid json at all")
        repairer = LLMArgumentRepairer(llm_provider=fake, model_id="claude-opus-4-8")

        args = {"city": "London"}
        result = await repairer.repair_arguments("get_weather", args, "error")
        assert result == {"city": "London"}

    @pytest.mark.asyncio
    async def test_repair_on_empty_response_falls_back(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.recovery.argument_repairer import LLMArgumentRepairer

        fake = FakeLLMProvider(default_response="")
        repairer = LLMArgumentRepairer(llm_provider=fake, model_id="claude-opus-4-8")

        args = {"query": "SELECT *"}
        result = await repairer.repair_arguments("query_database", args, "error")
        assert result == {"query": "SELECT *"}

    @pytest.mark.asyncio
    async def test_repair_on_partial_json_falls_back(self):
        from neo_mcp.planners.llm_provider import FakeLLMProvider
        from neo_mcp.recovery.argument_repairer import LLMArgumentRepairer

        fake = FakeLLMProvider(default_response='{"city": "Paris"')  # truncated JSON
        repairer = LLMArgumentRepairer(llm_provider=fake, model_id="claude-opus-4-8")

        args = {"city": "London"}
        result = await repairer.repair_arguments("get_weather", args, "error")
        assert result == {"city": "London"}