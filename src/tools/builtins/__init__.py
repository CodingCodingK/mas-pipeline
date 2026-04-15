"""Built-in tool pool: central registry of all available tool instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtins.memory import MemoryReadTool, MemoryWriteTool
from src.tools.builtins.project_info import (
    GetCurrentProjectTool,
    GetRunDetailsTool,
    ListProjectRunsTool,
)
from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.search_docs import SearchDocsTool
from src.tools.builtins.shell import ShellTool
from src.tools.builtins.web_search import WebSearchTool
from src.tools.builtins.write_file import WriteFileTool

if TYPE_CHECKING:
    from src.tools.base import Tool

# Tools that sub-agents are NOT allowed to use (prevent recursive spawning).
AGENT_DISALLOWED_TOOLS: set[str] = {"spawn_agent"}


def get_all_tools() -> dict[str, Tool]:
    """Return all built-in tool instances keyed by name.

    Lazy import for spawn_agent to avoid circular dependencies.
    """
    from src.tools.builtins.spawn_agent import SpawnAgentTool

    # Lazy import clawbot tools too — they depend on src.clawbot.session_state
    # which must not load before src.tools.base is importable.
    from src.clawbot.tools import get_clawbot_tools

    tools: list[Tool] = [
        ReadFileTool(),
        WriteFileTool(),
        ShellTool(),
        SpawnAgentTool(),
        WebSearchTool(),
        MemoryReadTool(),
        MemoryWriteTool(),
        SearchDocsTool(),
        GetCurrentProjectTool(),
        ListProjectRunsTool(),
        GetRunDetailsTool(),
    ]
    tools.extend(get_clawbot_tools())
    return {t.name: t for t in tools}
