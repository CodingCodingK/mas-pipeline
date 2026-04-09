"""HookRunner: register hooks, match by event + tool name, execute in parallel."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from src.hooks.config import HookConfig  # noqa: TC001 — used at runtime
from src.hooks.executors import execute_command_hook, execute_prompt_hook
from src.hooks.types import HookEvent, HookEventType, HookResult, aggregate_results

logger = logging.getLogger(__name__)

# Events where matcher filters by tool_name
_TOOL_EVENTS = {
    HookEventType.PRE_TOOL_USE,
    HookEventType.POST_TOOL_USE,
    HookEventType.POST_TOOL_USE_FAILURE,
}


@dataclass
class _RegisteredHook:
    """A hook registration with its matcher pattern."""
    matcher: str | None
    config: HookConfig


class HookRunner:
    """Manages hook registration and execution."""

    def __init__(self) -> None:
        self._hooks: dict[HookEventType, list[_RegisteredHook]] = defaultdict(list)

    def register(
        self,
        event_type: HookEventType,
        config: HookConfig,
        matcher: str | None = None,
    ) -> None:
        """Register a hook for an event type with an optional matcher pattern."""
        self._hooks[event_type].append(_RegisteredHook(matcher=matcher, config=config))

    async def run(self, event: HookEvent) -> HookResult:
        """Execute all matching hooks for an event and return aggregated result.

        Hooks run in parallel. Each hook has its own timeout.
        A failing hook does not block others.
        """
        matching = self._get_matching(event)
        if not matching:
            return HookResult()

        # Execute all matching hooks in parallel
        tasks = [self._execute_one(event, hook.config) for hook in matching]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions (logged inside _execute_one, but gather may also catch)
        hook_results: list[HookResult] = []
        for r in results:
            if isinstance(r, HookResult):
                hook_results.append(r)
            elif isinstance(r, Exception):
                logger.warning("Hook execution raised: %s", r)
                # Non-blocking: treat as allow
            else:
                hook_results.append(r)

        return aggregate_results(hook_results)

    def _get_matching(self, event: HookEvent) -> list[_RegisteredHook]:
        """Filter registered hooks by event type and matcher."""
        registered = self._hooks.get(event.event_type, [])
        if not registered:
            return []

        # For non-tool events, all hooks match (matcher is ignored)
        if event.event_type not in _TOOL_EVENTS:
            return registered

        # For tool events, filter by tool_name matcher
        tool_name = event.payload.get("tool_name", "")
        return [h for h in registered if _matcher_matches(h.matcher, tool_name)]

    async def _execute_one(self, event: HookEvent, config: HookConfig) -> HookResult:
        """Execute a single hook based on its type."""
        if config.type == "command":
            return await execute_command_hook(event, config)
        if config.type == "prompt":
            return await execute_prompt_hook(event, config)
        if config.type == "callable" and config.callable_fn is not None:
            try:
                return await asyncio.wait_for(
                    config.callable_fn(event),
                    timeout=config.timeout,
                )
            except TimeoutError:
                logger.warning("Callable hook timed out after %ds", config.timeout)
                return HookResult()
            except Exception:
                logger.warning("Callable hook raised", exc_info=True)
                return HookResult()

        logger.warning("Unknown hook type: %s", config.type)
        return HookResult()


def _matcher_matches(matcher: str | None, tool_name: str) -> bool:
    """Check if a matcher pattern matches a tool name.

    - None or empty string matches everything.
    - Supports | separated alternatives: "shell|spawn_agent"
    """
    if not matcher:
        return True
    return tool_name in matcher.split("|")
