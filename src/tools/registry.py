"""Tool registry: register, lookup, and export tool definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.tools.base import Tool


class ToolRegistry:
    """Manages tool registration and lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: '{tool.name}'")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"Tool not found: '{name}'") from None

    def list_definitions(self, names: list[str] | None = None) -> list[dict]:
        """Export OpenAI function calling format definitions.

        If *names* is provided, only matching tools are included.
        """
        tools = self._tools.values()
        if names is not None:
            name_set = set(names)
            tools = [t for t in tools if t.name in name_set]
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
