"""Hook executors: command (subprocess) and prompt (LLM)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from src.hooks.types import HookEvent, HookResult

if TYPE_CHECKING:
    from src.hooks.config import HookConfig

logger = logging.getLogger(__name__)


async def execute_command_hook(event: HookEvent, config: HookConfig) -> HookResult:
    """Execute a command hook via subprocess.

    Protocol:
    - stdin: HookEvent payload as JSON
    - stdout: optional JSON with HookResult fields
    - Exit code 0: allow (parse stdout if JSON)
    - Exit code 2: deny (blocking error)
    - Other exit codes: non-blocking error (logged, returns allow)
    - Timeout: non-blocking (logged, returns allow)
    """
    timeout = config.timeout or 30
    payload_json = json.dumps(event.payload, ensure_ascii=False, default=str)

    try:
        proc = await asyncio.create_subprocess_shell(
            config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=payload_json.encode()),
            timeout=timeout,
        )
    except TimeoutError:
        import contextlib
        logger.warning("Command hook timed out after %ds: %s", timeout, config.command)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()  # type: ignore[possibly-undefined]
        return HookResult(action="allow")
    except Exception as exc:
        logger.warning("Command hook failed to start: %s — %s", config.command, exc)
        return HookResult(action="allow")

    exit_code = proc.returncode
    stdout_str = stdout_bytes.decode(errors="replace").strip() if stdout_bytes else ""
    stderr_str = stderr_bytes.decode(errors="replace").strip() if stderr_bytes else ""

    # Exit code 2 = blocking deny
    if exit_code == 2:
        reason = stderr_str or stdout_str or "Blocked by hook"
        return HookResult(action="deny", reason=reason)

    # Exit code 0 = success, try to parse stdout as JSON
    if exit_code == 0:
        if stdout_str:
            try:
                data = json.loads(stdout_str)
                return HookResult(
                    action=data.get("action", "allow"),
                    reason=data.get("reason", ""),
                    updated_input=data.get("updated_input"),
                    additional_context=data.get("additional_context", ""),
                )
            except json.JSONDecodeError:
                pass  # Non-JSON stdout is fine, treat as allow
        return HookResult(action="allow")

    # Other exit codes = non-blocking error
    logger.warning(
        "Command hook exited with code %d: %s — stderr: %s",
        exit_code, config.command, stderr_str,
    )
    return HookResult(action="allow")


async def execute_prompt_hook(event: HookEvent, config: HookConfig) -> HookResult:
    """Execute a prompt hook via LLM call.

    Replaces $ARGUMENTS in the prompt template with the event payload JSON,
    calls the light tier model, and parses the response as HookResult.
    """
    from src.llm.router import route

    payload_json = json.dumps(event.payload, ensure_ascii=False, default=str)
    prompt_text = config.prompt.replace("$ARGUMENTS", payload_json)

    try:
        adapter = route("light")
        messages = [
            {"role": "system", "content": (
                "You are a hook evaluator. Analyze the tool call and respond with JSON: "
                '{"action": "allow"|"deny"|"modify", "reason": "...", "additional_context": "..."}'
                " Respond with ONLY the JSON object, no other text."
            )},
            {"role": "user", "content": prompt_text},
        ]
        response = await adapter.call(messages)

        if response.content:
            # Try to parse as JSON
            text = response.content.strip()
            # Handle markdown code blocks
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            try:
                data = json.loads(text)
                return HookResult(
                    action=data.get("action", "allow"),
                    reason=data.get("reason", ""),
                    updated_input=data.get("updated_input"),
                    additional_context=data.get("additional_context", ""),
                )
            except json.JSONDecodeError:
                logger.warning("Prompt hook returned non-JSON: %s", text[:200])

        return HookResult(action="allow")

    except Exception as exc:
        logger.warning("Prompt hook failed: %s", exc)
        return HookResult(action="allow")
