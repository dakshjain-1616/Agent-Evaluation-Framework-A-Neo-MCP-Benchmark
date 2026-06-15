"""Unit tests for ToolRegistry and ToolExecutor — no real API calls."""

import pytest

from neo_mcp.core.models import Step, Verdict
from neo_mcp.executor.registry import ToolExecutor, ToolRegistry


class TestToolRegistry:
    """Test ToolRegistry registration and lookup."""

    def setup_method(self):
        self.registry = ToolRegistry()

    def test_register_and_has_tool(self):
        self.registry.register("ping", lambda: "pong", description="Returns pong")
        assert self.registry.has_tool("ping") is True
        assert self.registry.has_tool("nonexistent") is False

    def test_register_and_get(self):
        fn = lambda x: x + 1
        self.registry.register("add_one", fn, input_schema={"type": "number"})
        tool = self.registry.get("add_one")
        assert tool["name"] == "add_one"
        assert tool["func"] is fn
        assert tool["input_schema"] == {"type": "number"}

    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("nope") is None

    def test_register_with_schemas(self):
        in_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        out_schema = {"type": "string"}
        self.registry.register("echo", lambda x: x, input_schema=in_schema, output_schema=out_schema)
        tool = self.registry.get("echo")
        assert tool["input_schema"] == in_schema
        assert tool["output_schema"] == out_schema

    def test_get_all_returns_all_tools(self):
        self.registry.register("a", lambda: 1)
        self.registry.register("b", lambda: 2)
        tools = self.registry.get_all()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"a", "b"}

    def test_get_descriptions(self):
        self.registry.register("alpha", lambda: 0, description="First tool")
        self.registry.register("beta", lambda: 0, description="Second tool")
        descs = self.registry.get_descriptions()
        assert len(descs) == 2
        desc_map = {d["name"]: d["description"] for d in descs}
        assert desc_map["alpha"] == "First tool"
        assert desc_map["beta"] == "Second tool"

    def test_register_overwrites_existing(self):
        self.registry.register("tool", lambda: "old")
        self.registry.register("tool", lambda: "new")
        tool = self.registry.get("tool")
        assert tool["func"]() == "new"


class TestToolExecutor:
    """Test ToolExecutor dispatch and error handling."""

    def setup_method(self):
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)

        self.registry.register(
            "ping",
            lambda: "pong",
            description="Returns pong",
            output_schema={"type": "string"},
        )
        self.registry.register(
            "echo",
            lambda msg: msg,
            description="Echoes a message",
            input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
        self.registry.register(
            "add",
            lambda a, b: a + b,
            description="Adds two numbers",
        )

    @pytest.mark.asyncio
    async def test_execute_successful_sync_tool(self):
        step = Step(step_id="s1", tool_name="ping", arguments={}, description="Ping step")
        result = await self.executor.execute_step(step)
        assert result.success is True
        assert result.output == "pong"
        assert result.error is None
        assert result.verdict == Verdict.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_sync_tool_with_args(self):
        step = Step(step_id="s2", tool_name="echo", arguments={"msg": "hello"}, description="Echo step")
        result = await self.executor.execute_step(step)
        assert result.success is True
        assert result.output == "hello"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        step = Step(step_id="s3", tool_name="nonexistent", arguments={}, description="Bad step")
        result = await self.executor.execute_step(step)
        assert result.success is False
        assert "Unknown tool" in result.error
        assert result.verdict == Verdict.FAILURE

    @pytest.mark.asyncio
    async def test_execute_failing_tool_wraps_exception(self):
        def failing_tool():
            raise ValueError("Something went wrong")

        self.registry.register("fail", failing_tool)

        step = Step(step_id="s4", tool_name="fail", arguments={}, description="Failing step")
        result = await self.executor.execute_step(step)
        assert result.success is False
        assert "Something went wrong" in result.error
        assert "ValueError" in result.exception_type
        assert result.verdict == Verdict.FAILURE

    @pytest.mark.asyncio
    async def test_execute_sync_tool_passes_args_correctly(self):
        self.registry.register("multiply", lambda x, y: x * y)
        step = Step(step_id="s5", tool_name="multiply", arguments={"x": 3, "y": 4}, description="Multiply")
        result = await self.executor.execute_step(step)
        assert result.success is True
        assert result.output == 12

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        async def async_echo(msg):
            return f"echo: {msg}"

        self.registry.register("async_echo", async_echo)
        step = Step(step_id="s6", tool_name="async_echo", arguments={"msg": "test"}, description="Async step")
        result = await self.executor.execute_step(step)
        assert result.success is True
        assert result.output == "echo: test"

    @pytest.mark.asyncio
    async def test_execute_missing_arg_raises_type_error(self):
        def requires_two(a, b):
            return a + b

        self.registry.register("req_two", requires_two)
        step = Step(step_id="s7", tool_name="req_two", arguments={"a": 1}, description="Missing b")
        result = await self.executor.execute_step(step)
        assert result.success is False
        assert "TypeError" in result.exception_type or "missing" in result.error.lower()

    @pytest.mark.asyncio
    async def test_step_result_has_step_reference(self):
        step = Step(step_id="s8", tool_name="ping", arguments={}, description="Ref step")
        result = await self.executor.execute_step(step)
        assert result.step is step or result.step.step_id == "s8"