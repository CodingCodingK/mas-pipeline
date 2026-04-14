"""Skill executor: variable substitution, inline and fork execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.skills.types import SkillResult

if TYPE_CHECKING:
    from src.skills.types import SkillDefinition

logger = logging.getLogger(__name__)


def substitute_variables(
    content: str,
    args: str,
    context: dict[str, Any],
) -> str:
    """Replace variable placeholders in skill content.

    Supported: $ARGUMENTS, ${PROJECT_ID}, ${AGENT_ID}, ${SKILL_DIR}.
    Missing values are replaced with empty string.
    """
    result = content.replace("$ARGUMENTS", args)
    result = result.replace("${PROJECT_ID}", str(context.get("project_id") or ""))
    result = result.replace("${AGENT_ID}", str(context.get("agent_id") or ""))
    result = result.replace("${SKILL_DIR}", str(context.get("skill_dir") or ""))
    return result


def execute_inline(
    skill: SkillDefinition,
    args: str,
    context: dict[str, Any],
) -> SkillResult:
    """Execute an inline skill: substitute variables and return prompt text."""
    output = substitute_variables(skill.content, args, context)
    return SkillResult(mode="inline", output=output, skill_name=skill.name)


async def execute_fork(
    skill: SkillDefinition,
    args: str,
    context: dict[str, Any],
) -> SkillResult:
    """Execute a fork skill: spawn isolated sub-agent, wait for result."""
    from src.agent.factory import create_agent
    from src.agent.loop import run_agent_to_completion
    from src.agent.state import ExitReason

    task_description = substitute_variables(skill.content, args, context)

    # Extract parent permission info from context
    permission_mode = context.get("permission_mode")
    parent_deny_rules = context.get("parent_deny_rules")

    if permission_mode is None:
        from src.permissions.types import PermissionMode
        permission_mode = PermissionMode.NORMAL

    try:
        state = await create_agent(
            role=skill.name,
            task_description=task_description,
            project_id=context.get("project_id"),
            run_id=context.get("run_id", ""),
            tools_override=skill.tools or None,
            abort_signal=context.get("abort_signal"),
            permission_mode=permission_mode,
            parent_deny_rules=parent_deny_rules,
        )

        run_result = await run_agent_to_completion(state)
        output = run_result.final_output
        exit_reason = run_result.exit_reason

        if exit_reason in (ExitReason.COMPLETED, ExitReason.MAX_TURNS):
            return SkillResult(
                mode="fork", output=output or "(no output)",
                skill_name=skill.name,
            )

        return SkillResult(
            mode="fork", output=f"[{exit_reason.value}] {output}",
            skill_name=skill.name, success=False,
        )

    except Exception as exc:
        logger.exception("Fork skill '%s' failed", skill.name)
        return SkillResult(
            mode="fork", output=f"[ERROR] {exc}",
            skill_name=skill.name, success=False,
        )
