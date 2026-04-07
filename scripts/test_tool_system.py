"""End-to-end verification for the tool system.

Tests:
- Registry: register, get, list_definitions
- Params: cast + validate
- Orchestrator: dispatch with concurrency partitioning
- Built-in tools: read_file, shell
"""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.llm.adapter import ToolCallRequest
from src.tools.base import ToolContext
from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.shell import ShellTool, _is_command_safe
from src.tools.orchestrator import ToolOrchestrator, partition_tool_calls
from src.tools.params import cast_params, validate_params
from src.tools.registry import ToolRegistry


def test_cast_params():
    print("=== cast_params ===")
    schema = {
        "properties": {
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "items": {"type": "array"},
        }
    }

    result = cast_params(
        {"count": "42", "ratio": "3.14", "flag": "true", "items": "[1,2,3]"},
        schema,
    )
    assert result["count"] == 42, f"Expected 42, got {result['count']}"
    assert result["ratio"] == 3.14, f"Expected 3.14, got {result['ratio']}"
    assert result["flag"] is True, f"Expected True, got {result['flag']}"
    assert result["items"] == [1, 2, 3], f"Expected [1,2,3], got {result['items']}"
    print("  cast str→int/float/bool/list: OK")

    # Non-convertible stays unchanged
    result2 = cast_params({"count": "abc"}, schema)
    assert result2["count"] == "abc"
    print("  non-convertible preserved: OK")


def test_validate_params():
    print("=== validate_params ===")
    schema = {
        "properties": {
            "file_path": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["file_path"],
    }

    errors = validate_params({"file_path": "test.py", "timeout": 30}, schema)
    assert errors == [], f"Expected no errors, got {errors}"
    print("  valid params: OK")

    errors = validate_params({"timeout": "not_a_number"}, schema)
    assert len(errors) == 2  # missing file_path + wrong type for timeout
    print(f"  invalid params ({len(errors)} errors): OK")


def test_registry():
    print("=== ToolRegistry ===")
    registry = ToolRegistry()
    rf = ReadFileTool()
    sh = ShellTool()
    registry.register(rf)
    registry.register(sh)

    assert registry.get("read_file") is rf
    assert registry.get("shell") is sh
    print("  register + get: OK")

    # Duplicate rejected
    try:
        registry.register(ReadFileTool())
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        print("  duplicate rejected: OK")

    # list_definitions
    defs = registry.list_definitions()
    assert len(defs) == 2
    names = {d["function"]["name"] for d in defs}
    assert names == {"read_file", "shell"}
    print("  list_definitions (all): OK")

    # Filtered
    defs_filtered = registry.list_definitions(names=["read_file"])
    assert len(defs_filtered) == 1
    assert defs_filtered[0]["function"]["name"] == "read_file"
    print("  list_definitions (filtered): OK")


def test_concurrency_safety():
    print("=== is_concurrency_safe ===")
    assert _is_command_safe("git log --oneline") is True
    assert _is_command_safe("ls -la") is True
    assert _is_command_safe("git log | head -20") is True
    assert _is_command_safe("cat file.txt") is True
    print("  safe commands: OK")

    assert _is_command_safe("python script.py") is False
    assert _is_command_safe("echo $HOME") is False
    assert _is_command_safe("ls > output.txt") is False
    assert _is_command_safe("rm -rf /tmp/x") is False
    assert _is_command_safe("cat file.txt | python -c 'import sys'") is False
    print("  unsafe commands: OK")


def test_partition():
    print("=== partition_tool_calls ===")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(ShellTool())

    calls = [
        ToolCallRequest(id="1", name="read_file", arguments={"file_path": "a.py"}),
        ToolCallRequest(id="2", name="read_file", arguments={"file_path": "b.py"}),
        ToolCallRequest(id="3", name="shell", arguments={"command": "rm -rf x"}),
        ToolCallRequest(id="4", name="read_file", arguments={"file_path": "c.py"}),
    ]
    batches = partition_tool_calls(calls, registry)
    assert len(batches) == 3, f"Expected 3 batches, got {len(batches)}"
    assert batches[0].is_concurrency_safe is True
    assert len(batches[0].items) == 2  # two read_files
    assert batches[1].is_concurrency_safe is False
    assert len(batches[1].items) == 1  # shell rm
    assert batches[2].is_concurrency_safe is True
    assert len(batches[2].items) == 1  # one read_file
    print("  [safe, safe, unsafe, safe] → 3 batches [2, 1, 1]: OK")


async def test_dispatch():
    print("=== ToolOrchestrator.dispatch ===")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(ShellTool())
    orch = ToolOrchestrator(registry)

    ctx = ToolContext(agent_id="test", run_id="run-1")

    # Test with read_file on this script itself
    this_file = os.path.abspath(__file__)
    calls = [
        ToolCallRequest(
            id="1",
            name="read_file",
            arguments={"file_path": this_file, "limit": 3},
        ),
        ToolCallRequest(
            id="2",
            name="shell",
            arguments={"command": "echo hello"},
        ),
    ]
    results = await orch.dispatch(calls, ctx)
    assert len(results) == 2
    assert results[0].success is True
    assert "test_tool_system" in results[0].output or "End-to-end" in results[0].output
    assert results[1].success is True
    assert "hello" in results[1].output
    print("  dispatch read_file + shell: OK")

    # Test param cast integration: timeout as string
    calls2 = [
        ToolCallRequest(
            id="3",
            name="shell",
            arguments={"command": "echo cast_test", "timeout": "30"},
        ),
    ]
    results2 = await orch.dispatch(calls2, ctx)
    assert results2[0].success is True
    assert "cast_test" in results2[0].output
    print("  param cast (timeout='30' → 30): OK")

    # Test unknown tool
    calls3 = [
        ToolCallRequest(id="4", name="nonexistent", arguments={}),
    ]
    results3 = await orch.dispatch(calls3, ctx)
    assert results3[0].success is False
    assert "unknown tool" in results3[0].output
    print("  unknown tool error: OK")


async def main():
    print("\n--- Tool System Verification ---\n")

    test_cast_params()
    test_validate_params()
    test_registry()
    test_concurrency_safety()
    test_partition()
    await test_dispatch()

    print("\n[PASS] All tool system tests passed!\n")


if __name__ == "__main__":
    asyncio.run(main())
