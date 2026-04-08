"""Verification for Phase 2.5 SubAgent mechanism.

Tests:
1. get_all_tools — global tool pool
2. create_agent — agent factory from role file
3. extract_final_output — output extraction
4. spawn_agent + task tracking — end-to-end with real LLM
"""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS_COUNT = 0


def check(label, condition, detail=""):
    global PASS_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [PASS] {label}", flush=True)
    else:
        print(f"  [FAIL] {label} — {detail}", flush=True)
        raise AssertionError(f"{label}: {detail}")


async def ensure_test_data():
    """Ensure user id=1 and project id=1 exist."""
    from sqlalchemy import text

    from src.db import get_db

    async with get_db() as session:
        r = await session.execute(text("SELECT id FROM users WHERE id=1"))
        if r.scalar() is None:
            await session.execute(
                text("INSERT INTO users (id, name, email) VALUES (1, 'test', 'test@test.com')")
            )
        r = await session.execute(text("SELECT id FROM projects WHERE id=1"))
        if r.scalar() is None:
            await session.execute(
                text(
                    "INSERT INTO projects (id, user_id, name, pipeline)"
                    " VALUES (1, 1, 'test', 'test')"
                )
            )


async def test_get_all_tools():
    print("\n=== 1. get_all_tools ===", flush=True)
    from src.tools.builtins import AGENT_DISALLOWED_TOOLS, get_all_tools

    tools = get_all_tools()
    check("returns dict", isinstance(tools, dict))
    check("has read_file", "read_file" in tools)
    check("has shell", "shell" in tools)
    check("has spawn_agent", "spawn_agent" in tools)
    check("has task_create", "task_create" in tools)
    check("has task_list", "task_list" in tools)
    check("has task_get", "task_get" in tools)
    check("has task_update", "task_update" in tools)
    check("spawn_agent in disallowed", "spawn_agent" in AGENT_DISALLOWED_TOOLS)


async def test_create_agent():
    print("\n=== 2. create_agent ===", flush=True)
    from src.agent.factory import create_agent
    from src.agent.state import AgentState

    state = await create_agent(
        role="general",
        task_description="Say hello.",
        project_id=None,
        run_id="test-run",
    )

    check("returns AgentState", isinstance(state, AgentState))
    check("has messages", len(state.messages) >= 2)
    check("system message first", state.messages[0]["role"] == "system")
    check(
        "user message with task",
        state.messages[-1]["role"] == "user"
        and "hello" in state.messages[-1]["content"].lower(),
    )
    check("agent_id correct", state.tool_context.agent_id == "test-run:general")

    tool_names = {d["function"]["name"] for d in state.tools.list_definitions()}
    check("has read_file", "read_file" in tool_names)
    check("has shell", "shell" in tool_names)
    check("no spawn_agent", "spawn_agent" not in tool_names)

    # Missing role
    try:
        await create_agent(role="nonexistent_xyz", task_description="test")
        check("missing role raises", False)
    except FileNotFoundError:
        check("missing role raises FileNotFoundError", True)


async def test_extract_final_output():
    print("\n=== 3. extract_final_output ===", flush=True)
    from src.tools.builtins.spawn_agent import extract_final_output

    msgs = [
        {"role": "assistant", "content": "First"},
        {"role": "assistant", "content": "Final answer"},
    ]
    check("last content", extract_final_output(msgs) == "Final answer")

    msgs = [
        {"role": "assistant", "content": "Good result"},
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
    ]
    check("backtrack past tool_calls", extract_final_output(msgs) == "Good result")

    msgs = [{"role": "assistant", "tool_calls": [{"id": "1"}]}]
    check("empty when no content", extract_final_output(msgs) == "")

    msgs = [
        {"role": "assistant", "content": "   "},
        {"role": "assistant", "content": "Real content"},
    ]
    check("skip whitespace", extract_final_output(msgs) == "Real content")


async def test_spawn_and_track():
    print("\n=== 4. spawn_agent + task tracking (real LLM) ===", flush=True)
    from src.engine.run import create_run
    from src.task.manager import get_task
    from src.tools.base import ToolContext
    from src.tools.builtins.spawn_agent import SpawnAgentTool
    from src.tools.builtins.task import TaskGetTool, TaskListTool

    run = await create_run(project_id=1)
    print(f"  run: id={run.id}, run_id={run.run_id}", flush=True)

    context = ToolContext(agent_id="coordinator", run_id=run.run_id, project_id=1)

    # Spawn
    spawn_tool = SpawnAgentTool()
    result = await spawn_tool.call(
        {
            "role": "general",
            "task_description": (
                "Read the file pyproject.toml and tell me the project name only."
                " One sentence max."
            ),
        },
        context,
    )
    check("spawn success", result.success)
    check("has task_id", "task_id" in result.metadata)
    task_id = result.metadata["task_id"]
    print(f"  spawned task_id={task_id}", flush=True)

    # Wait
    print("  waiting for sub-agent...", flush=True)
    task = None
    for _i in range(90):
        await asyncio.sleep(1)
        task = await get_task(task_id)
        if task and task.status in ("completed", "failed"):
            print(f"  done after {_i + 1}s: status={task.status}", flush=True)
            break
        if _i % 15 == 14:
            print(f"  still waiting... ({_i + 1}s)", flush=True)
    else:
        print("  TIMEOUT after 90s", flush=True)

    # task_list
    list_tool = TaskListTool()
    lr = await list_tool.call({}, context)
    check("task_list has tasks", "Tasks:" in lr.output)
    print(f"  task_list:\n{lr.output}", flush=True)

    # task_get
    get_tool = TaskGetTool()
    gr = await get_tool.call({"task_id": task_id}, context)
    check("task_get has details", f"id: {task_id}" in gr.output)
    terminal = "completed" in gr.output or "failed" in gr.output
    check("reached terminal state", terminal, gr.output[:200])
    print(f"  task_get:\n{gr.output[:500]}", flush=True)


async def main():
    print("\n--- Phase 2.5 SubAgent Verification ---", flush=True)

    # Tests 1-3: no DB needed
    await test_get_all_tools()
    await test_create_agent()
    await test_extract_final_output()

    # Test 4: needs DB + real LLM
    from src.db import close_db, init_db

    await init_db()
    try:
        await ensure_test_data()
        await test_spawn_and_track()
    finally:
        await close_db()

    print(f"\n[PASS] All {PASS_COUNT} checks passed!\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
