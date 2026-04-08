"""Tool system base: Tool ABC, ToolResult, ToolContext."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio


@dataclass
class ToolResult:
    """Standardized tool execution result."""

    output: str
    success: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolContext:
    """Execution context passed to every tool call."""

    agent_id: str
    run_id: str
    project_id: int | None = None
    abort_signal: asyncio.Event | None = None
    # Reference to parent AgentState (for coordinator notification queue).
    # TYPE_CHECKING-only import to avoid circular dependency.
    parent_state: Any = None


class Tool(ABC):
    """Abstract base class for all tools."""

    name: str
    description: str
    input_schema: dict  # JSON Schema

    def is_concurrency_safe(self, params: dict) -> bool:
        """Whether this invocation can run concurrently with other tools."""
        return False

    def is_read_only(self, params: dict) -> bool:
        """Whether this invocation is read-only (Phase 1: equals is_concurrency_safe)."""
        return self.is_concurrency_safe(params)

    @abstractmethod
    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        """Execute the tool and return a result."""
