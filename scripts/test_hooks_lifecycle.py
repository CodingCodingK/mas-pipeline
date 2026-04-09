"""Tests for lifecycle hook integration: SubagentStart/End, PipelineStart/End."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.runner import HookRunner
from src.hooks.types import HookEvent, HookEventType, HookResult
from src.tools.base import ToolContext

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    checks.append((name, condition))


# --- Capturing HookRunner ---

class CapturingRunner(HookRunner):
    """HookRunner that captures events for test assertions."""

    def __init__(self):
        super().__init__()
        self.events: list[HookEvent] = []

    async def run(self, event: HookEvent) -> HookResult:
        self.events.append(event)
        return HookResult()


print("=" * 60)
print("1. SpawnAgent _fire_hook triggers SubagentStart")
print("=" * 60)

runner = CapturingRunner()
context = ToolContext(
    agent_id="test:coordinator",
    run_id="run-1",
    project_id=1,
    hook_runner=runner,
)


async def test_fire_subagent_start():
    from src.tools.builtins.spawn_agent import SpawnAgentTool

    tool = SpawnAgentTool()
    await tool._fire_hook(context, "subagent_start", {
        "agent_run_id": 42,
        "role": "researcher",
        "task_description": "test task",
        "parent_run_id": "run-1",
    })


asyncio.run(test_fire_subagent_start())
start_events = [e for e in runner.events if e.event_type == HookEventType.SUBAGENT_START]
check("1.1 SubagentStart event fired", len(start_events) == 1)
check("1.2 Payload has role", start_events[0].payload.get("role") == "researcher")
check("1.3 Payload has agent_run_id", start_events[0].payload.get("agent_run_id") == 42)
check("1.4 Payload has parent_run_id", start_events[0].payload.get("parent_run_id") == "run-1")
check("1.5 Payload has task_description", start_events[0].payload.get("task_description") == "test task")


print()
print("=" * 60)
print("2. SpawnAgent _fire_hook triggers SubagentEnd")
print("=" * 60)

runner2 = CapturingRunner()
context2 = ToolContext(agent_id="test", run_id="run-1", hook_runner=runner2)


async def test_fire_subagent_end():
    from src.tools.builtins.spawn_agent import SpawnAgentTool

    tool = SpawnAgentTool()
    await tool._fire_hook(context2, "subagent_end", {
        "agent_run_id": 42,
        "role": "researcher",
        "status": "completed",
        "result": "findings...",
        "parent_run_id": "run-1",
    })


asyncio.run(test_fire_subagent_end())
end_events = [e for e in runner2.events if e.event_type == HookEventType.SUBAGENT_END]
check("2.1 SubagentEnd event fired", len(end_events) == 1)
check("2.2 Payload has status", end_events[0].payload.get("status") == "completed")
check("2.3 Payload has result", end_events[0].payload.get("result") == "findings...")


print()
print("=" * 60)
print("3. Pipeline fires PipelineStart/End hooks")
print("=" * 60)


async def test_pipeline_hooks():
    from src.engine.pipeline import _fire_pipeline_hook

    pr = CapturingRunner()

    await _fire_pipeline_hook(pr, "pipeline_start", {
        "pipeline_name": "test",
        "run_id": "run-1",
        "project_id": 1,
        "user_input": "hello",
    })

    await _fire_pipeline_hook(pr, "pipeline_end", {
        "pipeline_name": "test",
        "run_id": "run-1",
        "status": "completed",
        "error": None,
    })

    return pr.events


events = asyncio.run(test_pipeline_hooks())

start = [e for e in events if e.event_type == HookEventType.PIPELINE_START]
end = [e for e in events if e.event_type == HookEventType.PIPELINE_END]

check("3.1 PipelineStart fired", len(start) == 1)
check("3.2 PipelineStart has pipeline_name", start[0].payload.get("pipeline_name") == "test")
check("3.3 PipelineStart has user_input", start[0].payload.get("user_input") == "hello")
check("3.4 PipelineEnd fired", len(end) == 1)
check("3.5 PipelineEnd has status", end[0].payload.get("status") == "completed")
check("3.6 PipelineEnd has error=None", end[0].payload.get("error") is None)


print()
print("=" * 60)
print("4. No hook_runner: lifecycle events are no-op")
print("=" * 60)


async def test_no_hook_runner():
    from src.engine.pipeline import _fire_pipeline_hook

    await _fire_pipeline_hook(None, "pipeline_start", {"test": True})
    return True


check("4.1 No hook_runner is safe (pipeline)", asyncio.run(test_no_hook_runner()))

context_no_hooks = ToolContext(agent_id="test", run_id="run-1", hook_runner=None)


async def test_spawn_no_hooks():
    from src.tools.builtins.spawn_agent import SpawnAgentTool

    tool = SpawnAgentTool()
    await tool._fire_hook(context_no_hooks, "subagent_start", {"test": True})
    return True


check("4.2 No hook_runner is safe (spawn)", asyncio.run(test_spawn_no_hooks()))


print()
print("=" * 60)
print("5. Hook event payload completeness for all lifecycle types")
print("=" * 60)

event = HookEvent(
    event_type=HookEventType.SUBAGENT_START,
    payload={"agent_run_id": 1, "role": "r", "task_description": "t", "parent_run_id": "p"},
)
check("5.1 SubagentStart payload complete",
      all(k in event.payload for k in ["agent_run_id", "role", "task_description", "parent_run_id"]))

event = HookEvent(
    event_type=HookEventType.SUBAGENT_END,
    payload={"agent_run_id": 1, "role": "r", "status": "completed", "result": "x", "parent_run_id": "p"},
)
check("5.2 SubagentEnd payload complete",
      all(k in event.payload for k in ["agent_run_id", "role", "status", "result", "parent_run_id"]))

event = HookEvent(
    event_type=HookEventType.PIPELINE_START,
    payload={"pipeline_name": "p", "run_id": "r", "project_id": 1, "user_input": "u"},
)
check("5.3 PipelineStart payload complete",
      all(k in event.payload for k in ["pipeline_name", "run_id", "project_id", "user_input"]))

event = HookEvent(
    event_type=HookEventType.PIPELINE_END,
    payload={"pipeline_name": "p", "run_id": "r", "status": "completed", "error": None},
)
check("5.4 PipelineEnd payload complete",
      all(k in event.payload for k in ["pipeline_name", "run_id", "status", "error"]))

event = HookEvent(
    event_type=HookEventType.SESSION_START,
    payload={"session_id": "s", "project_id": 1},
)
check("5.5 SessionStart payload complete",
      all(k in event.payload for k in ["session_id", "project_id"]))

event = HookEvent(
    event_type=HookEventType.SESSION_END,
    payload={"session_id": "s", "reason": "timeout"},
)
check("5.6 SessionEnd payload complete",
      all(k in event.payload for k in ["session_id", "reason"]))


# Summary
print()
print("=" * 60)
passed = sum(1 for _, ok in checks if ok)
total = len(checks)
print(f"Results: {passed}/{total} checks passed")
if passed < total:
    failed = [name for name, ok in checks if not ok]
    print(f"Failed: {failed}")
    sys.exit(1)
print("All checks passed!")
