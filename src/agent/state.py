"""Agent state and exit reason definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.adapter import LLMAdapter
    from src.tools.base import ToolContext
    from src.tools.orchestrator import ToolOrchestrator
    from src.tools.registry import ToolRegistry


class ExitReason(str, Enum):
    """Why agent_loop terminated."""

    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    ABORT = "abort"
    ERROR = "error"
    TOKEN_LIMIT = "token_limit"
    # Phase 5: HOOK_STOPPED = "hook_stopped"


@dataclass
class AgentState:
    """All runtime dependencies for a single Agent execution.

    Identity (agent_id, run_id, project_id) lives in tool_context.
    """

    messages: list[dict] = field(default_factory=list)
    tools: ToolRegistry = field(default=None)  # type: ignore[assignment]
    adapter: LLMAdapter = field(default=None)  # type: ignore[assignment]
    orchestrator: ToolOrchestrator = field(default=None)  # type: ignore[assignment]
    tool_context: ToolContext = field(default=None)  # type: ignore[assignment]
    turn_count: int = 0
    max_turns: int = 50
    # Phase 3 compact
    has_attempted_reactive_compact: bool = False
    # Phase 6.1: SessionRunner waits while sub-agents are still running.
    # spawn_agent increments on launch and decrements when the background task finishes.
    running_agent_count: int = 0
    # Set by agent_loop generator before ending (replaces return value).
    exit_reason: ExitReason | None = None
