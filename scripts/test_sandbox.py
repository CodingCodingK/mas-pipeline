"""Unit tests for the sandbox package (types/detector/sync/wrapper) and ShellTool integration."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

from src.permissions.types import PermissionRule
from src.sandbox import (
    SandboxConfig,
    SandboxMode,
    SandboxPolicy,
    detect_sandbox_mode,
    is_wrapper_failure,
    policy_from_permission_rules,
    reset_sandbox_state,
    wrap_command,
)
from src.sandbox.detector import init_sandbox

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ─── 1. SandboxConfig defaults ────────────────────────────────────────────────


def test_config_defaults() -> None:
    print("\n[1] SandboxConfig defaults")
    cfg = SandboxConfig()
    check("enabled defaults to True", cfg.enabled is True)
    check("fail_if_unavailable defaults to False", cfg.fail_if_unavailable is False)

    cfg2 = SandboxConfig(enabled=False)
    check("enabled overridable", cfg2.enabled is False)


# ─── 2. detect_sandbox_mode ───────────────────────────────────────────────────


def test_detect_disabled() -> None:
    print("\n[2] detect_sandbox_mode")
    reset_sandbox_state()
    mode = detect_sandbox_mode(SandboxConfig(enabled=False))
    check("disabled by config", mode == SandboxMode.DISABLED)


def test_detect_linux_with_bwrap() -> None:
    reset_sandbox_state()
    with patch("src.sandbox.detector.platform.system", return_value="Linux"), patch(
        "src.sandbox.detector.shutil.which", return_value="/usr/bin/bwrap"
    ):
        mode = detect_sandbox_mode(SandboxConfig())
    check("linux + bwrap → LINUX_BWRAP", mode == SandboxMode.LINUX_BWRAP)


def test_detect_linux_without_bwrap_warn() -> None:
    reset_sandbox_state()
    with patch("src.sandbox.detector.platform.system", return_value="Linux"), patch(
        "src.sandbox.detector.shutil.which", return_value=None
    ):
        mode = detect_sandbox_mode(SandboxConfig())
    check("linux no bwrap warn → PASSTHROUGH", mode == SandboxMode.PASSTHROUGH)


def test_detect_linux_without_bwrap_strict() -> None:
    reset_sandbox_state()
    raised = False
    try:
        with patch("src.sandbox.detector.platform.system", return_value="Linux"), patch(
            "src.sandbox.detector.shutil.which", return_value=None
        ):
            detect_sandbox_mode(SandboxConfig(fail_if_unavailable=True))
    except RuntimeError:
        raised = True
    check("linux no bwrap strict → RuntimeError", raised)


def test_detect_macos() -> None:
    reset_sandbox_state()
    with patch("src.sandbox.detector.platform.system", return_value="Darwin"), patch(
        "src.sandbox.detector.os.path.exists", return_value=True
    ):
        mode = detect_sandbox_mode(SandboxConfig())
    check("macos → MACOS_SBX", mode == SandboxMode.MACOS_SBX)


def test_detect_windows() -> None:
    reset_sandbox_state()
    with patch("src.sandbox.detector.platform.system", return_value="Windows"):
        mode = detect_sandbox_mode(SandboxConfig())
    check("windows → PASSTHROUGH", mode == SandboxMode.PASSTHROUGH)


def test_init_sandbox_memoized() -> None:
    print("\n[3] init_sandbox memoization")
    reset_sandbox_state()
    call_count = {"n": 0}
    real_which = __import__("shutil").which

    def counting_which(name):
        call_count["n"] += 1
        return real_which(name)

    with patch("src.sandbox.detector.shutil.which", side_effect=counting_which):
        init_sandbox(SandboxConfig())
        init_sandbox(SandboxConfig())
        init_sandbox(SandboxConfig())
    check("which() probed at most once across 3 init calls", call_count["n"] <= 1, f"got {call_count['n']}")


# ─── 4. policy_from_permission_rules ──────────────────────────────────────────


def test_sync_edit_writable() -> None:
    print("\n[4] policy_from_permission_rules")
    rules = [PermissionRule(tool_name="edit", pattern="projects/**", action="allow")]
    p = policy_from_permission_rules(rules)
    check("edit allow → writable", "projects" in p.writable_paths)


def test_sync_read_readonly() -> None:
    rules = [PermissionRule(tool_name="read_file", pattern="docs/**", action="allow")]
    p = policy_from_permission_rules(rules)
    check("read_file allow → readonly", "docs" in p.readonly_paths)


def test_sync_deny_ignored() -> None:
    rules = [PermissionRule(tool_name="edit", pattern="secrets/**", action="deny")]
    p = policy_from_permission_rules(rules)
    check("deny rule contributes nothing", "secrets" not in p.writable_paths)


def test_sync_glob_reduced() -> None:
    rules = [PermissionRule(tool_name="write", pattern="src/**/*.py", action="allow")]
    p = policy_from_permission_rules(rules)
    check("glob reduced to literal prefix", p.writable_paths == ["src"], f"got {p.writable_paths}")


def test_sync_pure() -> None:
    rules = [PermissionRule(tool_name="edit", pattern="projects/**", action="allow")]
    p1 = policy_from_permission_rules(rules)
    p2 = policy_from_permission_rules(rules)
    check("pure: equal inputs → equal outputs",
          p1.writable_paths == p2.writable_paths and p1.readonly_paths == p2.readonly_paths)


# ─── 5. wrap_command ──────────────────────────────────────────────────────────


def test_wrap_passthrough_identity() -> None:
    print("\n[5] wrap_command")
    cmd = ["ls", "-la"]
    out = wrap_command(cmd, SandboxMode.PASSTHROUGH, SandboxPolicy())
    check("PASSTHROUGH identity", out == cmd)
    out2 = wrap_command(cmd, SandboxMode.DISABLED, SandboxPolicy())
    check("DISABLED identity", out2 == cmd)


def test_wrap_bwrap_shape() -> None:
    out = wrap_command(
        ["bash", "-c", "echo hi"],
        SandboxMode.LINUX_BWRAP,
        SandboxPolicy(writable_paths=["/repo/projects"]),
    )
    check("starts with bwrap", out[0] == "bwrap", f"got {out[:1]}")
    check("network unshared by default",
          "--unshare-all" in out and "--share-net" not in out)
    check("writable bound rw",
          any(out[i] == "--bind" and out[i + 1].endswith("projects") for i in range(len(out) - 1)))
    check("ends with original cmd",
          out[-3:] == ["bash", "-c", "echo hi"])


def test_wrap_bwrap_network_opt_in() -> None:
    out = wrap_command(
        ["echo"],
        SandboxMode.LINUX_BWRAP,
        SandboxPolicy(allow_network=True),
    )
    check("--share-net present when allow_network", "--share-net" in out)


def test_wrap_macos_profile() -> None:
    out = wrap_command(
        ["bash", "-c", "echo hi"],
        SandboxMode.MACOS_SBX,
        SandboxPolicy(writable_paths=["/Users/me/proj"]),
    )
    check("starts with sandbox-exec", out[0] == "sandbox-exec")
    check("has -p flag", out[1] == "-p")
    profile = out[2]
    check("profile has version 1", "(version 1)" in profile)
    check("profile denies default", "(deny default)" in profile)
    check("profile denies network", "(deny network*)" in profile)
    check("profile allows writable subpath",
          'file-write* (subpath "/Users/me/proj"' in profile or 'file-write* (subpath "' in profile)
    check("ends with original cmd", out[-3:] == ["bash", "-c", "echo hi"])


def test_is_wrapper_failure() -> None:
    print("\n[6] is_wrapper_failure")
    check("bwrap signature → True",
          is_wrapper_failure("bwrap: Can't bind /missing: ENOENT\n", 1))
    check("sandbox-exec signature → True",
          is_wrapper_failure("sandbox-exec: cannot read profile\n", 1))
    check("ordinary failure → False",
          not is_wrapper_failure("ls: cannot access /nope\n", 2))
    check("exit 0 → False",
          not is_wrapper_failure("bwrap: anything\n", 0))
    check("empty stderr → False", not is_wrapper_failure("", 1))


# ─── 7. ShellTool integration smoke (mocked subprocess) ───────────────────────


async def _run_shell(disable_sandbox: bool, mode: SandboxMode) -> tuple[bool, list]:
    """Run ShellTool.call with sandbox mode patched. Returns (used_exec, captured_argv)."""
    from src.tools.base import ToolContext
    from src.tools.builtins.shell import ShellTool

    captured: dict = {"argv": None, "used_exec": False}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"hello\n___CWD_MARKER___\n/tmp\n", b"")

    async def fake_exec(*argv, **kwargs):
        captured["used_exec"] = True
        captured["argv"] = list(argv)
        return _FakeProc()

    async def fake_shell(cmd, **kwargs):
        captured["used_exec"] = False
        captured["argv"] = cmd
        return _FakeProc()

    with patch("src.tools.builtins.shell.get_sandbox_mode", return_value=mode), patch(
        "asyncio.create_subprocess_exec", side_effect=fake_exec
    ), patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
        tool = ShellTool(cwd="/tmp")
        ctx = ToolContext(agent_id="a", run_id="r")
        params: dict = {"command": "echo hello"}
        if disable_sandbox:
            params["dangerously_disable_sandbox"] = True
        result = await tool.call(params, ctx)

    return captured["used_exec"], captured["argv"], result


async def test_shell_passthrough_uses_shell() -> None:
    print("\n[7] ShellTool integration")
    used_exec, argv, result = await _run_shell(False, SandboxMode.PASSTHROUGH)
    check("PASSTHROUGH uses create_subprocess_shell", used_exec is False)
    check("metadata sandbox_mode tagged", result.metadata.get("sandbox_mode") == "passthrough")


async def test_shell_bwrap_wraps() -> None:
    used_exec, argv, result = await _run_shell(False, SandboxMode.LINUX_BWRAP)
    check("LINUX_BWRAP uses create_subprocess_exec", used_exec is True)
    check("argv begins with bwrap", argv and argv[0] == "bwrap", f"argv[:1]={argv[:1] if argv else None}")
    check("metadata sandbox_mode = linux-bwrap",
          result.metadata.get("sandbox_mode") == "linux-bwrap")


async def test_shell_escape_hatch_bypasses() -> None:
    used_exec, argv, result = await _run_shell(True, SandboxMode.LINUX_BWRAP)
    check("escape hatch uses create_subprocess_shell", used_exec is False)
    check("metadata sandbox_mode = passthrough on escape",
          result.metadata.get("sandbox_mode") == "passthrough")


async def test_shell_wrapper_failure_metadata() -> None:
    from src.tools.base import ToolContext
    from src.tools.builtins.shell import ShellTool

    class _FakeProc:
        returncode = 1

        async def communicate(self):
            return (b"", b"bwrap: Can't bind /nope: ENOENT\n")

    async def fake_exec(*argv, **kwargs):
        return _FakeProc()

    with patch("src.tools.builtins.shell.get_sandbox_mode", return_value=SandboxMode.LINUX_BWRAP), patch(
        "asyncio.create_subprocess_exec", side_effect=fake_exec
    ):
        tool = ShellTool(cwd="/tmp")
        ctx = ToolContext(agent_id="a", run_id="r")
        result = await tool.call({"command": "echo hi"}, ctx)

    check("wrapper_failure tagged on bwrap stderr", result.metadata.get("wrapper_failure") is True)
    check("success False on wrapper failure", result.success is False)


# ─── runner ───────────────────────────────────────────────────────────────────


async def main() -> int:
    test_config_defaults()
    test_detect_disabled()
    test_detect_linux_with_bwrap()
    test_detect_linux_without_bwrap_warn()
    test_detect_linux_without_bwrap_strict()
    test_detect_macos()
    test_detect_windows()
    test_init_sandbox_memoized()

    test_sync_edit_writable()
    test_sync_read_readonly()
    test_sync_deny_ignored()
    test_sync_glob_reduced()
    test_sync_pure()

    test_wrap_passthrough_identity()
    test_wrap_bwrap_shape()
    test_wrap_bwrap_network_opt_in()
    test_wrap_macos_profile()
    test_is_wrapper_failure()

    await test_shell_passthrough_uses_shell()
    await test_shell_bwrap_wraps()
    await test_shell_escape_hatch_bypasses()
    await test_shell_wrapper_failure_metadata()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
