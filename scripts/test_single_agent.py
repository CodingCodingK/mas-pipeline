"""Phase 1 end-to-end verification: single Agent with real LLM.

Chain: parse role file -> build system prompt -> build messages
       -> AgentState -> agent_loop -> LLM -> tool call -> result -> final reply

Requires: config/settings.local.yaml with valid API key.
"""

import asyncio
import os
import sys

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from datetime import UTC, datetime

from src.agent.context import build_messages, build_system_prompt, parse_role_file
from src.agent.loop import agent_loop
from src.agent.state import AgentState, ExitReason
from src.llm.router import route
from src.tools.base import ToolContext
from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.shell import ShellTool
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry


async def main():
    print("\n--- Phase 1 End-to-End Verification ---\n")

    # 1. Parse role file
    print("1. Parsing role file: agents/general.md")
    role_path = os.path.join(PROJECT_ROOT, "agents", "general.md")
    meta, role_body = parse_role_file(role_path)
    print(f"   meta: {meta}")
    print(f"   model_tier: {meta.get('model_tier', 'N/A')}")
    print(f"   tools: {meta.get('tools', [])}")

    # 2. Build system prompt
    print("\n2. Building system prompt")
    system_prompt = build_system_prompt(role_body, PROJECT_ROOT)
    print(f"   prompt length: {len(system_prompt)} chars")

    # 3. Build messages
    print("\n3. Building messages")
    runtime_ctx = {
        "current_time": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "agent_id": "general-001",
    }
    user_input = (
        f"Read the first 5 lines of the file at {role_path} and tell me what role this agent has."
    )
    messages = build_messages(system_prompt, [], user_input, runtime_context=runtime_ctx)
    print(f"   messages count: {len(messages)}")
    print(f"   user input: {user_input}")

    # 4. Route to LLM adapter
    #    Use 'light' tier for testing (only openai provider configured).
    #    In production, create_agent (Phase 2.5) would use meta['model_tier'].
    print("\n4. Routing to LLM adapter")
    tier = "light"
    adapter = route(tier)
    print(f"   tier: {tier} -> model: {adapter.model}")

    # 5. Build tool registry (only tools declared in frontmatter)
    print("\n5. Setting up tools")
    registry = ToolRegistry()
    tool_map = {"read_file": ReadFileTool, "shell": ShellTool}
    declared_tools = meta.get("tools", [])
    for tool_name in declared_tools:
        cls = tool_map.get(tool_name)
        if cls:
            registry.register(cls())
    print(f"   registered: {[t['function']['name'] for t in registry.list_definitions()]}")

    # 6. Construct AgentState
    print("\n6. Constructing AgentState")
    orchestrator = ToolOrchestrator(registry)
    tool_context = ToolContext(agent_id="general-001", run_id="run-e2e-001")
    state = AgentState(
        messages=messages,
        tools=registry,
        adapter=adapter,
        orchestrator=orchestrator,
        tool_context=tool_context,
        max_turns=10,
    )

    # 7. Run agent loop
    print("\n7. Running agent_loop...")
    print("   " + "-" * 50)
    reason = await agent_loop(state)
    print("   " + "-" * 50)

    # 8. Report results
    print("\n8. Results:")
    print(f"   exit_reason: {reason}")
    print(f"   turn_count: {state.turn_count}")
    print(f"   total messages: {len(state.messages)}")

    # Show message flow
    print("\n   Message flow:")
    for i, msg in enumerate(state.messages):
        role = msg["role"]
        if role == "system":
            print(f"   [{i}] system ({len(msg['content'])} chars)")
        elif role == "user":
            content = msg["content"]
            print(f"   [{i}] user: {content[:80]}{'...' if len(content) > 80 else ''}")
        elif role == "assistant":
            if "tool_calls" in msg:
                calls = [tc["function"]["name"] for tc in msg["tool_calls"]]
                print(f"   [{i}] assistant -> tool_calls: {calls}")
            else:
                content = msg.get("content", "")
                print(f"   [{i}] assistant: {content[:80]}{'...' if len(content) > 80 else ''}")
        elif role == "tool":
            content = msg["content"]
            print(f"   [{i}] tool({msg['tool_call_id']}): {content[:60]}{'...' if len(content) > 60 else ''}")

    # Verify
    print("\n9. Verification:")
    if reason == ExitReason.COMPLETED:
        print("   [PASS] Agent completed successfully")
    else:
        print(f"   [WARN] Agent exited with: {reason}")

    if state.turn_count > 0:
        print(f"   [PASS] Agent used tools ({state.turn_count} tool round(s))")
    else:
        print("   [INFO] Agent completed without using tools")

    # Check for tool result messages
    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    if tool_msgs:
        print(f"   [PASS] Tool results fed back to LLM ({len(tool_msgs)} result(s))")
    else:
        print("   [INFO] No tool results in conversation")

    # Final assistant message should have content
    final = state.messages[-1]
    if final["role"] == "assistant" and final.get("content"):
        print(f"   [PASS] Final response: {final['content'][:100]}...")
    else:
        print(f"   [WARN] Last message is not assistant content: role={final['role']}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
