"""Built-in tool: shell — execute shell commands with cwd persistence."""

from __future__ import annotations

import asyncio
import logging
import os
import re

from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 30_000
_DEFAULT_TIMEOUT = 120

SAFE_PREFIXES = [
    "cat ",
    "ls ",
    "head ",
    "tail ",
    "wc ",
    "find ",
    "grep ",
    "rg ",
    "git log",
    "git status",
    "git diff",
    "git show",
    "git branch",
    "git tag",
    "pwd",
    "echo ",
    "which ",
    "type ",
    "file ",
    "python --version",
    "node --version",
]

# Separators for splitting compound commands
_SEPARATORS_RE = re.compile(r"\s*(?:&&|\|\||[;|])\s*")


def _is_command_safe(command: str) -> bool:
    """Check if a shell command is safe for concurrent execution.

    Rules:
    1. Variable expansion ($, backtick) → unsafe
    2. Output redirection (>) → unsafe
    3. Split by separators, each part must match SAFE_PREFIXES
    """
    # Variable expansion / command substitution → unpredictable
    if "$" in command or "`" in command:
        return False

    # Output redirection → may write files
    if ">" in command:
        return False

    # Split compound command and check each part
    parts = _SEPARATORS_RE.split(command)
    return all(_part_matches_prefix(p.strip()) for p in parts if p.strip())


def _part_matches_prefix(part: str) -> bool:
    return any(part.startswith(prefix) or part == prefix.strip() for prefix in SAFE_PREFIXES)


class ShellTool(Tool):
    name = "shell"
    description = (
        "Execute a shell command and return its output. "
        "The working directory persists across calls (cd is remembered)."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default {_DEFAULT_TIMEOUT}).",
            },
        },
        "required": ["command"],
    }

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or os.getcwd()

    def is_concurrency_safe(self, params: dict) -> bool:
        command = params.get("command", "")
        return _is_command_safe(command)

    # Sentinel to separate command output from pwd output
    _CWD_SENTINEL = "___CWD_MARKER___"

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        command: str = params["command"]
        timeout: int = params.get("timeout", _DEFAULT_TIMEOUT)

        # Append pwd to capture cwd after command (including cd effects).
        # Use a sentinel line so we can split command output from the pwd result.
        wrapped = f'{command}\necho "{self._CWD_SENTINEL}"\npwd'

        try:
            proc = await asyncio.create_subprocess_shell(
                wrapped,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            await proc.communicate()  # type: ignore[union-attr]
            return ToolResult(
                output=f"Error: command timed out after {timeout}s",
                success=False,
                metadata={"exit_code": -1},
            )
        except OSError as exc:
            return ToolResult(
                output=f"Error executing command: {exc}",
                success=False,
            )

        raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0

        # Split command output from cwd capture
        stdout = raw_stdout
        if self._CWD_SENTINEL in raw_stdout:
            parts = raw_stdout.split(self._CWD_SENTINEL, 1)
            stdout = parts[0].rstrip("\n")
            new_cwd = parts[1].strip()
            if new_cwd and os.path.isdir(new_cwd):
                self._cwd = new_cwd

        # Combine output
        output = stdout
        if stderr:
            output = f"{stdout}\n[stderr]\n{stderr}" if stdout else stderr

        # Truncate
        truncated = False
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n[truncated]"
            truncated = True

        return ToolResult(
            output=output,
            success=exit_code == 0,
            metadata={"exit_code": exit_code, "truncated": truncated},
        )
