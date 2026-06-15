from __future__ import annotations

from selfheal import ArgSpec, Failure, FailureClass, FunctionTool, SchemaRepairer


def _failure() -> Failure:
    return Failure(FailureClass.INVALID_ARGUMENT, "bad arg", "t", 1)


def _tool(schema):
    return FunctionTool("t", lambda **k: k, schema=schema)


def test_coerces_string_to_int():
    repairer = SchemaRepairer()
    tool = _tool({"value": ArgSpec(int)})
    out = repairer.repair(tool, {"value": "21"}, _failure())
    assert out == {"value": 21}


def test_drops_unknown_keys():
    repairer = SchemaRepairer()
    tool = _tool({"value": ArgSpec(int)})
    out = repairer.repair(tool, {"value": 3, "stray": "x"}, _failure())
    assert out == {"value": 3}


def test_fills_required_default_when_missing():
    repairer = SchemaRepairer()
    tool = _tool({"limit": ArgSpec(int, required=True, default=10)})
    out = repairer.repair(tool, {}, _failure())
    assert out == {"limit": 10}


def test_truncates_oversized_value():
    repairer = SchemaRepairer()
    tool = _tool({"text": ArgSpec(str, max_len=3)})
    out = repairer.repair(tool, {"text": "abcdef"}, _failure())
    assert out == {"text": "abc"}


def test_returns_none_when_nothing_to_fix():
    repairer = SchemaRepairer()
    tool = _tool({"value": ArgSpec(int)})
    assert repairer.repair(tool, {"value": 5}, _failure()) is None


def test_returns_none_without_schema():
    repairer = SchemaRepairer()
    tool = _tool({})
    assert repairer.repair(tool, {"value": "21"}, _failure()) is None


def test_unrepairable_value_falls_back_to_default():
    repairer = SchemaRepairer()
    tool = _tool({"value": ArgSpec(int, default=0)})
    out = repairer.repair(tool, {"value": "not-a-number"}, _failure())
    assert out == {"value": 0}
