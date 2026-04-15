"""persona_write — write the per-chat SOUL.md override.

This is clawbot's only mutation path for the bot's persona骨架. Scope is
strictly the **current chat** (channel + chat_id taken from the tool
context, never from parameters), so a call in one Discord group cannot
touch any other group's persona file.

Intent-routing rule (enforced by the description seen by the LLM, not by
code): call this tool ONLY when the user is telling you how the bot itself
should behave — personality, tone, fixed opening lines, reply format,
addressing preferences, emoji policy, bot self-identity. Everything else
(user role/expertise, project state, engineering preferences, external
references) is long-term memory and goes to `memory_write` instead.

Write semantics: full file replacement. LLM must reconstruct the complete
new SOUL body. The baseline `config/clawbot/SOUL.md` is visible in the
system prompt when no override exists — the LLM has everything it needs
to re-emit a coherent replacement.
"""

from __future__ import annotations

import logging

from src.clawbot.persona import write_persona_soul
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class PersonaWriteTool(Tool):
    name = "persona_write"
    description = (
        "Write the per-chat SOUL.md override for the current chat. "
        "Use ONLY when the user is telling you how the BOT ITSELF should "
        "behave in this specific chat — personality, tone, fixed opening "
        "lines, reply format, emoji policy, addressing preferences, bot "
        "self-identity. These belong in SOUL because they define the bot's "
        "骨架 for THIS chat, not facts about the user or project.\n\n"
        "For anything else — user's role/expertise, project decisions, "
        "engineering preferences, external references, workflow "
        "constraints — use memory_write instead.\n\n"
        "When in doubt, prefer memory_write. persona_write changes the "
        "bot's骨架 and should be high-confidence only.\n\n"
        "Write semantics: FULL REPLACEMENT. You must pass the complete new "
        "SOUL body in `content`, not a patch. The current SOUL is already "
        "visible in your system prompt — copy it and edit, don't try to "
        "emit only the delta. Preserve user's original wording verbatim "
        "for rule-like directives (fixed phrases, formats) — do not "
        "paraphrase or summarize."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "Full replacement body for this chat's SOUL.md. Must "
                    "include the complete persona definition, not just "
                    "additions. Rule-like content (fixed opening lines, "
                    "required phrases, formatting rules) must appear "
                    "verbatim in the user's original wording — do not "
                    "paraphrase."
                ),
            },
        },
        "required": ["content"],
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
                    "Error: persona_write is only available inside a "
                    "clawbot chat session (no channel/chat_id in context)."
                ),
                success=False,
            )

        content = params.get("content")
        if not isinstance(content, str) or not content.strip():
            return ToolResult(
                output="Error: content must be a non-empty string",
                success=False,
            )

        try:
            path = await write_persona_soul(
                channel=channel,
                chat_id=chat_id,
                content=content,
            )
        except ValueError as e:
            return ToolResult(output=f"Error: {e}", success=False)
        except OSError:
            logger.exception(
                "persona_write: filesystem write failed for %s:%s",
                channel,
                chat_id,
            )
            return ToolResult(
                output="Error: failed to write persona file (filesystem)",
                success=False,
            )

        return ToolResult(
            output=(
                f"SOUL override saved for {channel}:{chat_id}. "
                f"New persona will take effect on the next turn."
            ),
            success=True,
            metadata={"channel": channel, "chat_id": chat_id, "path": path},
        )
