"""Tool abstraction.

A :class:`Tool` is any named, callable unit of work the agent can invoke. Tools
declare an optional argument ``schema`` which the argument-repair layer uses to
coerce and fix malformed calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ArgSpec:
    """Lightweight description of a single argument, used for repair."""

    type: type
    required: bool = True
    default: Any = None
    max_len: int | None = None  # for str/list-like values


@runtime_checkable
class Tool(Protocol):
    """The contract every tool satisfies."""

    name: str
    schema: Mapping[str, ArgSpec]

    def run(self, **kwargs: Any) -> Any:
        ...


@dataclass
class FunctionTool:
    """Adapts a plain callable into a :class:`Tool`."""

    name: str
    func: Callable[..., Any]
    schema: Mapping[str, ArgSpec] = field(default_factory=dict)

    def run(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)


class ToolRegistry:
    """A name -> tool lookup with friendly errors."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"unknown tool {name!r}; registered: {sorted(self._tools)}"
            ) from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)
