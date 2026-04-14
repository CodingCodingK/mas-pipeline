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
    # Hook runner for lifecycle events (SubagentStart/End etc.)
    hook_runner: Any = None
    # Permission checker for SubAgent deny-rule inheritance
    permission_checker: Any = None
    # Phase 6.1: SessionRunner addressing — set when running under a SessionRunner.
    # spawn_agent uses these to persist task notifications and wake the parent runner.
    # Sub-agents inherit them so nested spawns route notifications to the same session.
    session_id: int | None = None
    conversation_id: int | None = None


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

    def normalize_params(self, params: dict) -> dict:
        """Normalize tool parameters before the PreToolUse hook sees them.

        Default: identity. Tools that accept path-like fields should override
        (e.g., write_file resolves file_path via os.path.realpath so that the
        permission layer sees the real destination, not the pre-traversal string).
        MUST NOT mutate the input dict; return a new dict if changes are needed.
        """
        return params

    @abstractmethod
    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        """Execute the tool and return a result."""
