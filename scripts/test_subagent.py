"""Verification for Phase 2.5 SubAgent mechanism.

Tests:
1. get_all_tools — global tool pool
2. create_agent — agent factory from role file
3. extract_final_output — output extraction
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


async def test_get_all_tools():
    print("\n=== 1. get_all_tools ===", flush=True)
    from src.tools.builtins import AGENT_DISALLOWED_TOOLS, get_all_tools

    tools = get_all_tools()
    check("returns dict", isinstance(tools, dict))
    check("has read_file", "read_file" in tools)
    check("has shell", "shell" in tools)
    check("has spawn_agent", "spawn_agent" in tools)
    check("no task_create (removed in Phase 2.4)", "task_create" not in tools)
    check("no task_list (removed in Phase 2.4)", "task_list" not in tools)
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
        permission_mode="default",
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
        await create_agent(
            role="nonexistent_xyz",
            task_description="test",
            permission_mode="default",
        )
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


async def main():
    print("\n--- Phase 2.5 SubAgent Verification ---", flush=True)

    # Tests 1-3: no DB needed
    # (Test 4 — real-LLM spawn+task-tracking — removed in Phase 2.4
    #  after task_* tools were deleted in the Task → AgentRun rename)
    await test_get_all_tools()
    await test_create_agent()
    await test_extract_final_output()

    print(f"\n[PASS] All {PASS_COUNT} checks passed!\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
