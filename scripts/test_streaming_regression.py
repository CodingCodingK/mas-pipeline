"""Regression tests for streaming-adapted callers.

Tests 9.1 through 9.3 from the streaming tasks.
Verifies spawn_agent and pipeline engine work with run_agent_to_completion.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.state import AgentState, ExitReason
from src.llm.adapter import LLMResponse, ToolCallRequest, Usage
from src.streaming.events import StreamEvent
from src.tools.base import ToolContext, ToolResult
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


def make_simple_adapter():
    """Create an adapter that yields a simple text response."""
    adapter = MagicMock()
    adapter.model = "test-model"
    adapter.call = AsyncMock(return_value=LLMResponse(content="summary", usage=Usage(5, 5, 0)))

    async def fake_call_stream(messages, tool_defs, **kwargs):
        yield StreamEvent(type="text_delta", content="test response")
        yield StreamEvent(type="usage", usage=Usage(10, 5, 0))
        yield StreamEvent(type="done", finish_reason="stop")

    adapter.call_stream = fake_call_stream
    return adapter


def make_state_with_adapter(adapter) -> AgentState:
    registry = ToolRegistry()
    orchestrator = MagicMock(spec=ToolOrchestrator)
    orchestrator.dispatch = AsyncMock(return_value=[])

    tool_context = ToolContext(
        agent_id="test-agent",
        run_id="test-run",
        project_id=1,
        abort_signal=None,
    )

    return AgentState(
        messages=[
            {"role": "system", "content": "Test agent"},
            {"role": "user", "content": "Do something"},
        ],
        tools=registry,
        adapter=adapter,
        orchestrator=orchestrator,
        tool_context=tool_context,
    )


# ── 9.1 spawn_agent regression ──────────────────────────────


def test_spawn_agent_regression():
    print("\n=== 9.1 spawn_agent regression test ===")

    from src.tools.builtins.spawn_agent import SpawnAgentTool, extract_final_output

    tool = SpawnAgentTool()
    adapter = make_simple_adapter()

    persisted: list[tuple[int, dict]] = []

    async def fake_append_message(conv_id: int, message: dict) -> None:
        persisted.append((conv_id, message))

    context = ToolContext(
        agent_id="parent",
        run_id="run-1",
        project_id=1,
        abort_signal=None,
        session_id=77,
        conversation_id=88,
    )

    async def run():
        test_state = make_state_with_adapter(adapter)

        with patch("src.tools.builtins.spawn_agent.SpawnAgentTool._resolve_run_id", new_callable=AsyncMock, return_value=1), \
             patch("src.agent.runs.create_agent_run", new_callable=AsyncMock) as mock_create, \
             patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=test_state), \
             patch("src.agent.runs.complete_agent_run", new_callable=AsyncMock), \
             patch("src.session.manager.append_message", new=fake_append_message), \
             patch("src.tools.builtins.spawn_agent.SpawnAgentTool._notify_session_wakeup", new_callable=AsyncMock), \
             patch("src.engine.session_registry.get_runner", return_value=None):
            mock_run = MagicMock()
            mock_run.id = 42
            mock_create.return_value = mock_run

            result = await tool.call(
                {"role": "researcher", "task_description": "find stuff"},
                context,
            )

            check("spawn returns immediately", "agent_run_id=42" in result.output)

            # Wait for background task
            await asyncio.sleep(0.5)

            check("notification persisted", len(persisted) == 1)
            if persisted:
                conv_id, msg = persisted[0]
                check("persisted to parent conversation", conv_id == 88)
                check(
                    "notification message is task_notification",
                    msg.get("metadata", {}).get("kind") == "task_notification",
                )
                check(
                    "notification metadata has role",
                    msg.get("metadata", {}).get("sub_agent_role") == "researcher",
                )
                check(
                    "notification metadata has completed status",
                    msg.get("metadata", {}).get("status") == "completed",
                )

    asyncio.run(run())


# ── 9.2 pipeline engine regression ──────────────────────────


def test_pipeline_regression():
    print("\n=== 9.2 pipeline engine regression test ===")

    # Test that _execute_node uses run_agent_to_completion
    # by checking the import path
    from src.agent.loop import run_agent_to_completion

    adapter = make_simple_adapter()
    state = make_state_with_adapter(adapter)

    async def run():
        exit_reason = await run_agent_to_completion(state)
        check("run_agent_to_completion returns COMPLETED", exit_reason == ExitReason.COMPLETED)
        check("state has assistant message", any(m.get("role") == "assistant" for m in state.messages))
        check("assistant content accumulated", state.messages[-1].get("content") == "test response")

    asyncio.run(run())

    # Verify pipeline code imports run_agent_to_completion (not agent_loop directly)
    import inspect
    from src.engine import pipeline
    source = inspect.getsource(pipeline)
    check("pipeline imports run_agent_to_completion", "run_agent_to_completion" in source)
    check("pipeline does not call agent_loop directly", "await agent_loop(" not in source)


# ── Run all ──────────────────────────────────────────────────


if __name__ == "__main__":
    test_spawn_agent_regression()
    test_pipeline_regression()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
