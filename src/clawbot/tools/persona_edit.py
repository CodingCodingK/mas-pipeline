"""persona_edit — unique string replacement on this chat's SOUL.md.

Companion to `persona_write` for targeted patches. Mirrors CC's Edit tool
semantics: exact substring match, must be unique, fails loudly on
ambiguity so the LLM is forced to expand context rather than guess.

When to use which:

  persona_write  → you want to redo the whole SOUL (new structure, full
                   rewrite, first-time personalization). Higher risk of
                   dropping lines if LLM paraphrases.

  persona_edit   → you want to add/remove/change ONE specific thing and
                   leave the rest alone. Safer for incremental tweaks
                   ("加一条固定开场白"、"改一下称呼"、"删掉某条规则").

The baseline `config/clawbot/SOUL.md` is never mutated. If no override
exists yet, the edit reads baseline as source and writes the patched
result as a new override file — so the chat starts having its own
SOUL from the first successful edit onward.
"""

from __future__ import annotations

import logging

from src.clawbot.persona import edit_persona_soul
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class PersonaEditTool(Tool):
    name = "persona_edit"
    description = (
        "Apply a unique string replacement to the current chat's SOUL.md. "
        "Use for targeted edits — adding a single rule, changing a phrase, "
        "deleting a line — when you want to preserve the rest of the "
        "persona unchanged. The baseline SOUL is visible in your system "
        "prompt; copy the exact substring to replace and pass it as "
        "`old_string`, then pass the replacement as `new_string`.\n\n"
        "`old_string` MUST appear in the current SOUL exactly once. If it "
        "matches zero times the tool fails (you copied it wrong or it's "
        "not there); if it matches multiple times the tool fails "
        "(expand `old_string` with more surrounding context until exactly "
        "one match remains).\n\n"
        "Preserve user's original wording verbatim for rule-like content. "
        "If the user says '先回你好我是助手', the replacement must contain "
        "the exact phrase `你好，我是助手` — do not paraphrase.\n\n"
        "Use `persona_write` instead when you want to replace the whole "
        "SOUL body (new structure, first-time personalization, or a "
        "rewrite so large that multiple edits would be messier than a "
        "full rewrite)."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "old_string": {
                "type": "string",
                "description": (
                    "Exact substring to find in the current SOUL. Must "
                    "appear exactly once. Whitespace, punctuation, and "
                    "newlines all matter — copy from the system prompt "
                    "literally."
                ),
            },
            "new_string": {
                "type": "string",
                "description": (
                    "Replacement text. May be empty to delete the match. "
                    "For rule-like additions, include the user's original "
                    "wording verbatim."
                ),
            },
        },
        "required": ["old_string", "new_string"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return False

    def is_read_only(self, params: dict) -> bool:
        return False

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        channel = context.channel
        chat_id = context.chat_id
        if not channel or not chat_id:
            return ToolResult(
                output=(
                    "Error: persona_edit is only available inside a "
                    "clawbot chat session (no channel/chat_id in context)."
                ),
                success=False,
            )

        old_string = params.get("old_string")
        new_string = params.get("new_string")
        if not isinstance(old_string, str) or old_string == "":
            return ToolResult(
                output="Error: old_string must be a non-empty string",
                success=False,
            )
        if not isinstance(new_string, str):
            return ToolResult(
                output="Error: new_string must be a string",
                success=False,
            )

        try:
            path = await edit_persona_soul(
                channel=channel,
                chat_id=chat_id,
                old_string=old_string,
                new_string=new_string,
            )
        except ValueError as e:
            return ToolResult(output=f"Error: {e}", success=False)
        except OSError:
            logger.exception(
                "persona_edit: filesystem write failed for %s:%s",
                channel,
                chat_id,
            )
            return ToolResult(
                output="Error: failed to write persona file (filesystem)",
                success=False,
            )

        return ToolResult(
            output=(
                f"SOUL patched for {channel}:{chat_id}. "
                f"New persona will take effect on the next turn."
            ),
            success=True,
            metadata={"channel": channel, "chat_id": chat_id, "path": path},
        )
