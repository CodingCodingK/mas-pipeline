"""Coordinator unit tests: CoordinatorResult, routing logic (mock Pipeline/Agent)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.coordinator import CoordinatorResult, coordinator_loop, run_coordinator
from src.engine.pipeline import PipelineResult
from src.agent.state import AgentState, ExitReason
from src.tools.base import ToolContext

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ── 1. CoordinatorResult construction ─────────────────────

print("\n=== 1. CoordinatorResult construction ===")

r1 = CoordinatorResult(
    run_id="abc123",
    mode="pipeline",
    output="Final blog post",
    node_outputs={"research": "data", "draft": "text"},
)
check("Pipeline result mode", r1.mode == "pipeline")
check("Pipeline result output", r1.output == "Final blog post")
check("Pipeline result node_outputs", r1.node_outputs == {"research": "data", "draft": "text"})
check("Pipeline result agent_runs is None", r1.agent_runs is None)

r2 = CoordinatorResult(
    run_id="def456",
    mode="autonomous",
    output="Task completed",
    agent_runs=[{"id": 1, "role": "general", "status": "completed", "result": "done"}],
)
check("Autonomous result mode", r2.mode == "autonomous")
check("Autonomous result agent_runs", len(r2.agent_runs) == 1)
check("Autonomous result node_outputs is None", r2.node_outputs is None)

# ── 2. coordinator_loop: no agents → immediate exit ──────

print("\n=== 2. coordinator_loop: immediate exit ===")


async def test_coordinator_loop_immediate_exit():
    """agent_loop completes with no running agents → coordinator_loop exits."""

    state = AgentState()
    state.tool_context = ToolContext(agent_id="test", run_id="r1")

    with patch("src.agent.loop.agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = ExitReason.COMPLETED
        result = await coordinator_loop(state)

    check("Immediate exit returns COMPLETED", result == ExitReason.COMPLETED)
    check("notification_queue initialized", state.notification_queue is not None)
    check("running_agent_count is 0", state.running_agent_count == 0)
    check("agent_loop called once", mock_loop.call_count == 1)


asyncio.run(test_coordinator_loop_immediate_exit())

# ── 3. coordinator_loop: notification re-entry ───────────

print("\n=== 3. coordinator_loop: notification re-entry ===")


async def test_coordinator_loop_reentry():
    """agent_loop exits with running agents → wait for notification → re-enter."""

    state = AgentState()
    state.tool_context = ToolContext(agent_id="test", run_id="r1")

    call_count = 0

    async def mock_agent_loop(s):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: simulate spawning an agent
            s.running_agent_count = 1
            # Schedule a notification to arrive
            async def push_notification():
                await asyncio.sleep(0.01)
                await s.notification_queue.put({
                    "agent_run_id": 42,
                    "role": "general",
                    "status": "completed",
                    "result": "done",
                    "message": "<task-notification>\n<agent-run-id>42</agent-run-id>\n<role>general</role>\n<status>completed</status>\n<result>done</result>\n</task-notification>",
                })
                s.running_agent_count = 0
            asyncio.create_task(push_notification())
            return ExitReason.COMPLETED
        else:
            # Second call: all agents done
            return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        result = await coordinator_loop(state)

    check("Re-entry returns COMPLETED", result == ExitReason.COMPLETED)
    check("agent_loop called twice", call_count == 2)
    # Verify notification was injected as user message
    user_msgs = [m for m in state.messages if m.get("role") == "user"]
    check("Notification injected as user message", len(user_msgs) == 1)
    check(
        "Notification contains task-notification XML",
        "<task-notification>" in user_msgs[0]["content"],
    )


asyncio.run(test_coordinator_loop_reentry())

# ── 4. run_coordinator routing: pipeline mode ────────────

print("\n=== 4. run_coordinator routing: pipeline mode ===")


async def test_run_coordinator_pipeline():
    """Project with pipeline field → execute_pipeline path."""

    mock_project = MagicMock()
    mock_project.pipeline = "test_linear"
    mock_project.id = 1

    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_abc"
    mock_wf_run.id = 1

    mock_pipeline_result = PipelineResult(
        run_id="run_abc",
        status="completed",
        outputs={"research": "data", "draft": "text"},
        final_output="Final output",
    )

    with (
        patch("src.db.get_db") as mock_get_db,
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.engine.pipeline.execute_pipeline", new_callable=AsyncMock, return_value=mock_pipeline_result),
    ):
        # Mock DB session to return project
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_project
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_db.return_value = mock_ctx

        # Also mock the yaml file existence check
        with patch.object(Path, "is_file", return_value=True):
            result = await run_coordinator(project_id=1, user_input="Write a blog")

    check("Pipeline mode result", result.mode == "pipeline")
    check("Pipeline mode output", result.output == "Final output")
    check("Pipeline mode node_outputs", result.node_outputs == {"research": "data", "draft": "text"})
    check("Pipeline mode run_id", result.run_id == "run_abc")


asyncio.run(test_run_coordinator_pipeline())

# ── 5. run_coordinator routing: autonomous mode ──────────

print("\n=== 5. run_coordinator routing: autonomous mode ===")


async def test_run_coordinator_autonomous():
    """Project without pipeline → coordinator_loop path."""

    mock_project = MagicMock()
    mock_project.pipeline = ""  # No pipeline
    mock_project.id = 2

    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_def"
    mock_wf_run.id = 2

    mock_state = AgentState()
    mock_state.messages = [
        {"role": "system", "content": "You are coordinator"},
        {"role": "user", "content": "Do something"},
        {"role": "assistant", "content": "Here is the result."},
    ]
    mock_state.tool_context = ToolContext(agent_id="test", run_id="run_def")

    with (
        patch("src.db.get_db") as mock_get_db,
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=mock_state),
        patch("src.engine.coordinator.coordinator_loop", new_callable=AsyncMock, return_value=ExitReason.COMPLETED),
        patch("src.tools.builtins.spawn_agent.extract_final_output", return_value="Here is the result."),
        patch("src.agent.runs.list_agent_runs", new_callable=AsyncMock, return_value=[]),
        patch("src.engine.run.finish_run", new_callable=AsyncMock),
    ):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = mock_project
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_db.return_value = mock_ctx

        result = await run_coordinator(project_id=2, user_input="Do something")

    check("Autonomous mode result", result.mode == "autonomous")
    check("Autonomous mode output", result.output == "Here is the result.")
    check("Autonomous mode agent_runs", result.agent_runs == [])
    check("Autonomous mode run_id", result.run_id == "run_def")


asyncio.run(test_run_coordinator_autonomous())

# ── 6. run_coordinator: project not found ────────────────

print("\n=== 6. run_coordinator: error cases ===")


async def test_run_coordinator_project_not_found():
    """Nonexistent project_id → ValueError."""

    with patch("src.db.get_db") as mock_get_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_db.return_value = mock_ctx

        try:
            await run_coordinator(project_id=999, user_input="test")
            check("Project not found raises", False, "no exception raised")
        except ValueError as e:
            check("Project not found raises ValueError", "999" in str(e))


asyncio.run(test_run_coordinator_project_not_found())

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
