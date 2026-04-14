"""Unit tests for WriteFileTool.

Verifies basic write semantics (new file, overwrite, append, auto-mkdir),
realpath normalization via normalize_params, OS-error handling, and
global tool pool registration.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.base import ToolContext
from src.tools.builtins import get_all_tools
from src.tools.builtins.write_file import WriteFileTool


def _ctx() -> ToolContext:
    return ToolContext(agent_id="t", run_id="r")


async def test_write_new_file() -> None:
    print("=== write_file: new file ===")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "a", "b", "out.txt")
        tool = WriteFileTool()
        result = await tool.call(
            {"file_path": target, "content": "hello"}, _ctx()
        )
        assert result.success, result.output
        assert os.path.isfile(target)
        with open(target, encoding="utf-8") as f:
            assert f.read() == "hello"
        assert "Wrote 5 bytes" in result.output
        assert result.metadata["bytes"] == 5
        print("  created parent dirs + wrote content: OK")


async def test_overwrite_existing() -> None:
    print("=== write_file: overwrite ===")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "x.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("old")
        tool = WriteFileTool()
        result = await tool.call(
            {"file_path": target, "content": "new"}, _ctx()
        )
        assert result.success
        with open(target, encoding="utf-8") as f:
            assert f.read() == "new"
        print("  overwritten: OK")


async def test_append_mode() -> None:
    print("=== write_file: append ===")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "x.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\n")
        tool = WriteFileTool()
        result = await tool.call(
            {"file_path": target, "content": "two\n", "append": True}, _ctx()
        )
        assert result.success
        with open(target, encoding="utf-8") as f:
            assert f.read() == "one\ntwo\n"
        print("  appended: OK")


def test_normalize_params_realpath() -> None:
    print("=== write_file: normalize_params realpath ===")
    tool = WriteFileTool()
    # Relative traversal should resolve via realpath and then re-relativize
    # against cwd so permission rules like write_file(src/**) can match.
    normalized = tool.normalize_params(
        {"file_path": "projects/../src/exploit.py", "content": "x"}
    )
    # Must end with src/exploit.py regardless of absolute vs relative form
    assert normalized["file_path"].endswith("src/exploit.py"), normalized["file_path"]
    # Forward slashes only (Windows backslashes stripped)
    assert "\\" not in normalized["file_path"]
    # Original dict must NOT be mutated
    original = {"file_path": "projects/../src/exploit.py", "content": "x"}
    tool.normalize_params(original)
    assert original["file_path"] == "projects/../src/exploit.py"
    print("  realpath resolves traversal, no mutation: OK")


def test_normalize_params_outside_cwd_stays_absolute() -> None:
    print("=== write_file: normalize_params outside cwd ===")
    tool = WriteFileTool()
    # A path that resolves outside cwd should stay absolute (not become ../../...)
    import tempfile as _tf
    outside = _tf.gettempdir() + "/mas_pipeline_test_outside.txt"
    normalized = tool.normalize_params({"file_path": outside, "content": "x"})
    # Either absolute path or the relpath form — both acceptable, but must
    # NOT start with "..". If outside is not under cwd, we expect absolute.
    assert not normalized["file_path"].startswith(".."), normalized["file_path"]
    print("  outside-cwd path handled: OK")


def test_normalize_params_missing_path() -> None:
    print("=== write_file: normalize_params with empty path ===")
    tool = WriteFileTool()
    # Graceful no-op when file_path is missing or empty (validation catches it later)
    assert tool.normalize_params({"content": "x"}) == {"content": "x"}
    assert tool.normalize_params({"file_path": "", "content": "x"})["file_path"] == ""
    print("  empty/missing path tolerated: OK")


async def test_os_error_returns_tool_result() -> None:
    print("=== write_file: OS error path ===")
    tool = WriteFileTool()
    # Write to a path where the parent is a file, not a directory → OSError on mkdir
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        bad = os.path.join(blocker, "child.txt")  # parent is a file
        result = await tool.call(
            {"file_path": bad, "content": "y"}, _ctx()
        )
        assert result.success is False
        assert "Error" in result.output
        print("  OS error surfaces as ToolResult(success=False): OK")


def test_pool_registration() -> None:
    print("=== write_file: get_all_tools pool ===")
    pool = get_all_tools()
    assert "write_file" in pool
    assert isinstance(pool["write_file"], WriteFileTool)
    assert len(pool) == 8, f"expected 8 tools, got {len(pool)}: {list(pool)}"
    print(f"  write_file registered, pool size = {len(pool)}: OK")


async def main() -> None:
    print("\n--- WriteFileTool Verification ---\n")
    await test_write_new_file()
    await test_overwrite_existing()
    await test_append_mode()
    test_normalize_params_realpath()
    test_normalize_params_outside_cwd_stays_absolute()
    test_normalize_params_missing_path()
    await test_os_error_returns_tool_result()
    test_pool_registration()
    print("\n[PASS] All WriteFileTool tests passed!\n")


if __name__ == "__main__":
    asyncio.run(main())
