"""Built-in tool: skill — invoke a registered skill by name."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.skills.executor import execute_fork, execute_inline
from src.tools.base import Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    from src.skills.types import SkillDefinition

logger = logging.getLogger(__name__)


class SkillTool(Tool):
    """LLM-invocable tool for triggering skills."""

    name = "skill"
    description = (
        "Invoke a skill (reusable prompt template). "
        "Available skills are listed in the system prompt. "
        "Use this tool when a skill matches your current task."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to invoke.",
            },
            "args": {
                "type": "string",
                "description": "Arguments to pass to the skill (replaces $ARGUMENTS).",
                "default": "",
            },
        },
        "required": ["skill_name"],
    }

    def __init__(self, available_skills: dict[str, SkillDefinition]) -> None:
        self._skills = available_skills

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        skill_name: str = params["skill_name"]
        args: str = params.get("args", "")

        skill = self._skills.get(skill_name)
        if skill is None:
            return ToolResult(
                output=f"Skill '{skill_name}' not found. Available: {', '.join(self._skills)}",
                success=False,
            )

        # Build execution context dict
        exec_ctx = {
            "project_id": context.project_id,
            "agent_id": context.agent_id,
            "run_id": context.run_id,
            "skill_dir": "",
            "abort_signal": context.abort_signal,
        }

        # Inherit permission from parent
        if context.permission_checker is not None:
            exec_ctx["permission_mode"] = context.permission_checker._mode
            exec_ctx["parent_deny_rules"] = context.permission_checker.get_deny_rules()

        if skill.context == "fork":
            result = await execute_fork(skill, args, exec_ctx)
            return ToolResult(
                output=result.output,
                success=result.success,
                metadata={"status": "forked", "skill_name": skill_name},
            )

        # inline
        result = execute_inline(skill, args, exec_ctx)
        return ToolResult(
            output=result.output,
            success=result.success,
            metadata={"status": "inline", "skill_name": skill_name},
        )
