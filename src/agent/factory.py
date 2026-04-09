"""Agent factory: create an independent AgentState from a role file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

from src.agent.context import build_messages, build_system_prompt, parse_role_file
from src.agent.state import AgentState
from src.hooks.config import load_hooks_from_frontmatter, load_hooks_from_settings
from src.hooks.runner import HookRunner
from src.llm.router import route
from src.project.config import get_settings
from src.tools.base import ToolContext
from src.tools.builtins import AGENT_DISALLOWED_TOOLS, get_all_tools
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Default agents directory relative to project root
_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


async def create_agent(
    role: str,
    task_description: str,
    project_id: int | None = None,
    run_id: str = "",
    tools_override: list[str] | None = None,
    max_turns: int = 30,
    abort_signal: asyncio.Event | None = None,
) -> AgentState:
    """Create an independent AgentState from a role file.

    Args:
        role: Role file name without .md extension (e.g. "researcher").
        task_description: Injected as the first user message.
        project_id: Project context for tool calls.
        run_id: Pipeline run ID for tool context.
        tools_override: If provided, replaces the role file's tool whitelist.
        max_turns: Maximum agent loop iterations.
        abort_signal: Shared cancellation event (parent + child).

    Returns:
        A fully configured AgentState ready for agent_loop().
    """
    # 1. Parse role file
    role_path = _AGENTS_DIR / f"{role}.md"
    if not role_path.is_file():
        raise FileNotFoundError(f"Role file not found: {role_path}")

    metadata, role_body = parse_role_file(str(role_path))

    # 2. Route adapter from model_tier
    model_tier = metadata.get("model_tier", "medium")
    adapter = route(model_tier)

    # 3. Build tool registry (whitelist - disallowed)
    tool_names = tools_override or metadata.get("tools", [])
    all_tools = get_all_tools()

    registry = ToolRegistry()
    for name in tool_names:
        if name in AGENT_DISALLOWED_TOOLS:
            continue
        if name in all_tools:
            registry.register(all_tools[name])
        else:
            logger.warning("Tool '%s' requested by role '%s' not found, skipping", name, role)

    # 4. Build hook runner (global + role-level hooks)
    hook_runner = _build_hook_runner(metadata)

    # 5. Build orchestrator + context
    orchestrator = ToolOrchestrator(registry, hook_runner=hook_runner)
    agent_id = f"{run_id}:{role}" if run_id else role
    tool_context = ToolContext(
        agent_id=agent_id,
        run_id=run_id,
        project_id=project_id,
        abort_signal=abort_signal,
        hook_runner=hook_runner,
    )

    # 6. Build messages
    system_prompt = build_system_prompt(role_body)
    messages = build_messages(
        system_prompt=system_prompt,
        history=[],
        user_input=task_description,
    )

    # 7. Assemble state
    return AgentState(
        messages=messages,
        tools=registry,
        adapter=adapter,
        orchestrator=orchestrator,
        tool_context=tool_context,
        max_turns=max_turns,
    )


def _build_hook_runner(metadata: dict) -> HookRunner:
    """Build a HookRunner with global hooks from settings + role hooks from frontmatter."""
    runner = HookRunner()

    # Load global hooks from settings.yaml
    settings = get_settings()
    for event_type, matcher, config in load_hooks_from_settings(settings.hooks):
        runner.register(event_type, config, matcher=matcher)

    # Load role-specific hooks from frontmatter
    frontmatter_hooks = metadata.get("hooks", {})
    if frontmatter_hooks:
        for event_type, matcher, config in load_hooks_from_frontmatter(frontmatter_hooks):
            runner.register(event_type, config, matcher=matcher)

    return runner
