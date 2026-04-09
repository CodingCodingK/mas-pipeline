"""Tool orchestrator: partition, dispatch, and collect tool call results."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.tools.base import Tool, ToolContext, ToolResult
from src.tools.params import cast_params, validate_params

if TYPE_CHECKING:
    from src.hooks.runner import HookRunner
    from src.llm.adapter import ToolCallRequest
    from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 10


@dataclass
class _Batch:
    is_concurrency_safe: bool
    items: list[tuple[ToolCallRequest, Tool]]


def partition_tool_calls(
    tool_calls: list[ToolCallRequest],
    registry: ToolRegistry,
) -> list[_Batch]:
    """Split tool calls into consecutive safe/unsafe batches.

    Consecutive concurrency-safe calls merge into one batch.
    Each non-safe call becomes its own batch.
    Unknown tools are treated as unsafe.
    """
    batches: list[_Batch] = []
    for tc in tool_calls:
        try:
            tool = registry.get(tc.name)
        except KeyError:
            tool = None

        safe = False
        if tool is not None:
            try:
                safe = tool.is_concurrency_safe(tc.arguments)
            except Exception:
                safe = False

        if safe and batches and batches[-1].is_concurrency_safe:
            batches[-1].items.append((tc, tool))  # type: ignore[arg-type]
        else:
            batches.append(_Batch(is_concurrency_safe=safe, items=[(tc, tool)]))  # type: ignore[arg-type]

    return batches


class ToolOrchestrator:
    """Dispatches tool calls with concurrency control."""

    def __init__(self, registry: ToolRegistry, hook_runner: HookRunner | None = None) -> None:
        self.registry = registry
        self.hook_runner = hook_runner

    async def dispatch(
        self,
        tool_calls: list[ToolCallRequest],
        context: ToolContext,
    ) -> list[ToolResult]:
        """Execute tool calls respecting concurrency safety.

        Returns results in the same order as *tool_calls*.
        """
        # Build ordered result slots
        results: dict[str, ToolResult] = {}

        for batch in partition_tool_calls(tool_calls, self.registry):
            if batch.is_concurrency_safe:
                sem = asyncio.Semaphore(_MAX_CONCURRENCY)
                await asyncio.gather(
                    *(self._run_with_sem(sem, tc, tool, context, results)
                      for tc, tool in batch.items)
                )
            else:
                for tc, tool in batch.items:
                    results[tc.id] = await self._execute_one(tc, tool, context)

        return [results[tc.id] for tc in tool_calls]

    async def _run_with_sem(
        self,
        sem: asyncio.Semaphore,
        tc: ToolCallRequest,
        tool: Tool,
        context: ToolContext,
        results: dict[str, ToolResult],
    ) -> None:
        async with sem:
            results[tc.id] = await self._execute_one(tc, tool, context)

    async def _execute_one(
        self,
        tc: ToolCallRequest,
        tool: Tool | None,
        context: ToolContext,
    ) -> ToolResult:
        if tool is None:
            return ToolResult(
                output=f"Error: unknown tool '{tc.name}'",
                success=False,
            )

        # Cast → validate → call
        params = cast_params(tc.arguments, tool.input_schema)
        errors = validate_params(params, tool.input_schema)
        if errors:
            msg = f"Parameter validation failed for '{tc.name}':\n" + "\n".join(
                f"  - {e}" for e in errors
            )
            return ToolResult(output=msg, success=False)

        # --- PreToolUse hooks ---
        if self.hook_runner:
            from src.hooks.types import HookEvent, HookEventType

            pre_event = HookEvent(
                event_type=HookEventType.PRE_TOOL_USE,
                payload={
                    "tool_name": tc.name,
                    "tool_input": params,
                    "agent_id": context.agent_id,
                    "run_id": context.run_id,
                },
            )
            pre_result = await self.hook_runner.run(pre_event)

            if pre_result.action == "deny":
                return ToolResult(
                    output=f"Hook denied: {pre_result.reason}",
                    success=False,
                )
            if pre_result.action == "modify" and pre_result.updated_input is not None:
                params = pre_result.updated_input

        # --- Execute tool ---
        try:
            result = await tool.call(params, context)
        except Exception as exc:
            logger.exception("Tool '%s' raised an exception", tc.name)
            result = ToolResult(
                output=f"Error executing '{tc.name}': {exc}",
                success=False,
            )

        # --- PostToolUse / PostToolUseFailure hooks ---
        if self.hook_runner:
            from src.hooks.types import HookEvent, HookEventType

            if result.success:
                post_event = HookEvent(
                    event_type=HookEventType.POST_TOOL_USE,
                    payload={
                        "tool_name": tc.name,
                        "tool_input": params,
                        "tool_output": result.output,
                        "success": True,
                        "agent_id": context.agent_id,
                        "run_id": context.run_id,
                    },
                )
            else:
                post_event = HookEvent(
                    event_type=HookEventType.POST_TOOL_USE_FAILURE,
                    payload={
                        "tool_name": tc.name,
                        "tool_input": params,
                        "error": result.output,
                        "agent_id": context.agent_id,
                        "run_id": context.run_id,
                    },
                )
            post_result = await self.hook_runner.run(post_event)

            if post_result.additional_context:
                result = ToolResult(
                    output=result.output + "\n\n" + post_result.additional_context,
                    success=result.success,
                    metadata=result.metadata,
                )

        return result
