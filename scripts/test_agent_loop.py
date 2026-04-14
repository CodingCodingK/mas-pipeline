"""End-to-end verification for the agent loop.

Tests:
- ReAct cycle: LLM -> tool call -> result -> LLM -> final reply
- Exit conditions: COMPLETED, MAX_TURNS
- Message format correctness
"""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.loop import run_agent_to_completion
from src.agent.messages import format_assistant_msg, format_tool_msg, format_user_msg
from src.agent.state import AgentState, ExitReason
from src.llm.adapter import LLMAdapter, LLMResponse, ToolCallRequest, Usage
from src.streaming.events import StreamEvent
from src.tools.base import ToolContext, ToolResult
from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.shell import ShellTool
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry


async def _response_to_stream(resp: LLMResponse):
    """Convert a full LLMResponse into a stream of StreamEvent (for mocks)."""
    if resp.content:
        yield StreamEvent(type="text_delta", content=resp.content)
    for tc in resp.tool_calls or []:
        yield StreamEvent(type="tool_end", tool_call=tc)
    if resp.usage:
        yield StreamEvent(type="usage", usage=resp.usage)
    yield StreamEvent(type="done", finish_reason=resp.finish_reason or "stop")

# --- Mock adapter that simulates LLM responses ---


class MockAdapter(LLMAdapter):
    """Returns pre-scripted responses in sequence."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        if self._call_count >= len(self._responses):
            return LLMResponse(content="[no more scripted responses]")
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp

    async def call_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ):
        resp = await self.call(messages, tools, **kwargs)
        async for event in _response_to_stream(resp):
            yield event


class FailingAdapter(LLMAdapter):
    """Always raises an exception."""

    async def call(self, messages, tools=None, **kwargs):
        raise ConnectionError("LLM unreachable")

    async def call_stream(self, messages, tools=None, **kwargs):
        raise ConnectionError("LLM unreachable")
        yield  # unreachable; makes this an async generator


# --- Helper to build a standard AgentState ---


def make_state(
    adapter: LLMAdapter,
    messages: list[dict] | None = None,
    max_turns: int = 50,
    abort_signal: asyncio.Event | None = None,
) -> AgentState:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(ShellTool())
    orchestrator = ToolOrchestrator(registry)
    ctx = ToolContext(
        agent_id="test-agent",
        run_id="run-1",
        abort_signal=abort_signal,
    )
    return AgentState(
        messages=messages or [format_user_msg("hello")],
        tools=registry,
        adapter=adapter,
        orchestrator=orchestrator,
        tool_context=ctx,
        max_turns=max_turns,
    )


# --- Tests ---


def test_format_assistant_msg():
    print("=== format_assistant_msg ===")

    # Content only
    resp = LLMResponse(content="Hello!", usage=Usage(10, 5, 0))
    msg = format_assistant_msg(resp)
    assert msg["role"] == "assistant"
    assert msg["content"] == "Hello!"
    assert "tool_calls" not in msg
    print("  content only: OK")

    # Tool calls
    resp2 = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id="tc_1", name="read_file", arguments={"file_path": "x.py"})
        ],
    )
    msg2 = format_assistant_msg(resp2)
    assert msg2["role"] == "assistant"
    assert "content" not in msg2
    assert len(msg2["tool_calls"]) == 1
    tc = msg2["tool_calls"][0]
    assert tc["id"] == "tc_1"
    assert tc["function"]["name"] == "read_file"
    assert isinstance(tc["function"]["arguments"], dict)
    print("  tool calls (arguments as dict): OK")

    # Thinking field
    resp3 = LLMResponse(content="answer", thinking="let me think...")
    msg3 = format_assistant_msg(resp3)
    assert msg3["thinking"] == "let me think..."
    print("  thinking field: OK")


def test_format_tool_msg():
    print("=== format_tool_msg ===")
    result = ToolResult(output="file contents here", success=True)
    msg = format_tool_msg("tc_1", result)
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "tc_1"
    assert msg["content"] == "file contents here"
    print("  tool result message: OK")


def test_format_user_msg():
    print("=== format_user_msg ===")
    msg = format_user_msg("what is this?")
    assert msg["role"] == "user"
    assert msg["content"] == "what is this?"
    print("  user message: OK")


def test_exit_reason_is_str():
    print("=== ExitReason ===")
    assert ExitReason.COMPLETED == "completed"
    assert ExitReason.MAX_TURNS == "max_turns"
    assert ExitReason.ABORT == "abort"
    assert ExitReason.ERROR == "error"
    print("  str enum values: OK")


async def test_completed_no_tools():
    print("=== agent_loop: COMPLETED (no tool calls) ===")
    adapter = MockAdapter([
        LLMResponse(content="I don't need any tools for this.", usage=Usage(10, 8, 0)),
    ])
    state = make_state(adapter)
    result = await run_agent_to_completion(state)
    assert result.exit_reason == ExitReason.COMPLETED
    assert state.turn_count == 0  # no tool round happened
    # Messages: [user, assistant]
    assert len(state.messages) == 2
    assert state.messages[1]["role"] == "assistant"
    assert state.messages[1]["content"] == "I don't need any tools for this."
    print("  single turn, no tools: OK")


async def test_react_cycle():
    print("=== agent_loop: ReAct cycle ===")
    this_file = os.path.abspath(__file__)
    adapter = MockAdapter([
        # Turn 1: LLM requests read_file
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="tc_1",
                    name="read_file",
                    arguments={"file_path": this_file, "limit": 3},
                )
            ],
            usage=Usage(20, 10, 0),
        ),
        # Turn 2: LLM gives final answer
        LLMResponse(content="The file starts with a docstring.", usage=Usage(30, 15, 0)),
    ])
    state = make_state(adapter)
    result = await run_agent_to_completion(state)
    assert result.exit_reason == ExitReason.COMPLETED
    assert state.turn_count == 1  # one tool round

    # Messages: [user, assistant(tool_call), tool_result, assistant(content)]
    assert len(state.messages) == 4
    assert state.messages[0]["role"] == "user"
    assert state.messages[1]["role"] == "assistant"
    assert "tool_calls" in state.messages[1]
    assert state.messages[2]["role"] == "tool"
    assert state.messages[2]["tool_call_id"] == "tc_1"
    assert "test_agent_loop" in state.messages[2]["content"] or "End-to-end" in state.messages[2]["content"]
    assert state.messages[3]["role"] == "assistant"
    assert state.messages[3]["content"] == "The file starts with a docstring."
    print("  LLM -> read_file -> result -> LLM -> done: OK")


async def test_max_turns():
    print("=== agent_loop: MAX_TURNS ===")
    # Adapter always requests a tool call (never finishes)
    endless_responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id=f"tc_{i}", name="shell", arguments={"command": "echo hi"})
            ],
            usage=Usage(5, 5, 0),
        )
        for i in range(10)
    ]
    state = make_state(MockAdapter(endless_responses), max_turns=2)
    result = await run_agent_to_completion(state)
    assert result.exit_reason == ExitReason.MAX_TURNS
    assert state.turn_count == 2
    print("  max_turns=2 triggered: OK")


async def test_error():
    print("=== agent_loop: ERROR ===")
    state = make_state(FailingAdapter())
    result = await run_agent_to_completion(state)
    assert result.exit_reason == ExitReason.ERROR
    assert state.turn_count == 0
    print("  adapter exception -> ERROR: OK")


async def test_abort():
    print("=== agent_loop: ABORT ===")
    abort = asyncio.Event()
    abort.set()  # pre-set: should abort immediately
    adapter = MockAdapter([
        LLMResponse(content="should not reach here"),
    ])
    state = make_state(adapter, abort_signal=abort)
    result = await run_agent_to_completion(state)
    assert result.exit_reason == ExitReason.ABORT
    # Adapter should not have been called
    assert adapter._call_count == 0
    print("  pre-set abort signal: OK")


async def test_message_format():
    print("=== Message format validation ===")
    adapter = MockAdapter([
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc_a", name="shell", arguments={"command": "echo test"}),
                ToolCallRequest(id="tc_b", name="read_file", arguments={"file_path": __file__}),
            ],
            usage=Usage(15, 10, 0),
        ),
        LLMResponse(content="Done.", usage=Usage(10, 5, 0)),
    ])
    state = make_state(adapter)
    await run_agent_to_completion(state)

    # Check assistant message with tool_calls
    assistant_msg = state.messages[1]
    assert assistant_msg["role"] == "assistant"
    for tc in assistant_msg["tool_calls"]:
        assert "id" in tc
        assert tc["type"] == "function"
        assert "name" in tc["function"]
        assert isinstance(tc["function"]["arguments"], dict)
    print("  assistant tool_calls format: OK")

    # Check tool result messages
    tool_msg_1 = state.messages[2]
    tool_msg_2 = state.messages[3]
    assert tool_msg_1["role"] == "tool"
    assert tool_msg_1["tool_call_id"] == "tc_a"
    assert tool_msg_2["role"] == "tool"
    assert tool_msg_2["tool_call_id"] == "tc_b"
    print("  tool result format: OK")

    # Check final assistant message
    final = state.messages[4]
    assert final["role"] == "assistant"
    assert final["content"] == "Done."
    print("  final assistant message: OK")


async def main():
    print("\n--- Agent Loop Verification ---\n")

    test_format_assistant_msg()
    test_format_tool_msg()
    test_format_user_msg()
    test_exit_reason_is_str()
    await test_completed_no_tools()
    await test_react_cycle()
    await test_max_turns()
    await test_error()
    await test_abort()
    await test_message_format()

    print("\n[PASS] All agent loop tests passed!\n")


if __name__ == "__main__":
    asyncio.run(main())
