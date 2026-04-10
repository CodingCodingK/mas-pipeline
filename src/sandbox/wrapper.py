"""Translate (cmd, mode, policy) → wrapped argv list. No subprocess work here."""

from __future__ import annotations

import os

from src.sandbox.types import SandboxMode, SandboxPolicy

# Linux base read-only layer — present on essentially every distro
_LINUX_BASE_RO = ["/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin"]


def wrap_command(
    cmd: list[str],
    mode: SandboxMode,
    policy: SandboxPolicy,
) -> list[str]:
    """Return an argv list that runs `cmd` inside the chosen sandbox primitive.

    For PASSTHROUGH and DISABLED, returns `cmd` unchanged.
    """
    if mode == SandboxMode.LINUX_BWRAP:
        return _wrap_bwrap(cmd, policy)
    if mode == SandboxMode.MACOS_SBX:
        return _wrap_sandbox_exec(cmd, policy)
    return list(cmd)


def _wrap_bwrap(cmd: list[str], policy: SandboxPolicy) -> list[str]:
    argv: list[str] = ["bwrap", "--die-with-parent", "--unshare-all"]

    if policy.allow_network:
        argv.append("--share-net")

    # Read-only base layer (skip non-existent paths so we don't confuse bwrap)
    for path in _LINUX_BASE_RO:
        if os.path.exists(path):
            argv.extend(["--ro-bind", path, path])

    # Policy-supplied writable paths
    for path in policy.writable_paths:
        abs_path = os.path.abspath(path)
        argv.extend(["--bind", abs_path, abs_path])

    # Policy-supplied additional read-only paths
    for path in policy.readonly_paths:
        abs_path = os.path.abspath(path)
        argv.extend(["--ro-bind", abs_path, abs_path])

    argv.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"])
    argv.append("--")
    argv.extend(cmd)
    return argv


def _wrap_sandbox_exec(cmd: list[str], policy: SandboxPolicy) -> list[str]:
    profile = _build_sbpl_profile(policy)
    return ["sandbox-exec", "-p", profile, *cmd]


def _build_sbpl_profile(policy: SandboxPolicy) -> str:
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow process-exec)",
        "(allow signal)",
        "(allow sysctl-read)",
        "(allow file-read*)",
    ]
    for path in policy.writable_paths:
        abs_path = os.path.abspath(path)
        # Escape any embedded quotes by removing them — paths shouldn't contain quotes
        safe = abs_path.replace('"', "")
        lines.append(f'(allow file-write* (subpath "{safe}"))')

    if policy.allow_network:
        lines.append("(allow network*)")
    else:
        lines.append("(deny network*)")

    return "\n".join(lines)


# bwrap and sandbox-exec error signatures we use to tag wrapper failures
_BWRAP_SIGS = ("bwrap: ",)
_SBX_SIGS = ("sandbox-exec: ",)


def is_wrapper_failure(stderr: str, exit_code: int) -> bool:
    """True if the captured stderr looks like a sandbox setup error,
    not a failure of the user command itself."""
    if exit_code == 0:
        return False
    if not stderr:
        return False
    for line in stderr.splitlines():
        line = line.lstrip()
        if any(line.startswith(sig) for sig in _BWRAP_SIGS):
            return True
        if any(line.startswith(sig) for sig in _SBX_SIGS):
            return True
    return False
