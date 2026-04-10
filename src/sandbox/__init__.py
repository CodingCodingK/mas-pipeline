"""Process-level sandbox layer for ShellTool.

Wraps shell commands with bubblewrap (Linux), sandbox-exec (macOS), or
passes through (Windows / binary missing). The kernel does the enforcement;
this package only translates Permission rules into the right CLI flags.
"""

from src.sandbox.detector import (
    detect_sandbox_mode,
    get_sandbox_mode,
    init_sandbox,
    reset_sandbox_state,
)
from src.sandbox.sync import policy_from_permission_rules
from src.sandbox.types import SandboxConfig, SandboxMode, SandboxPolicy
from src.sandbox.wrapper import is_wrapper_failure, wrap_command

__all__ = [
    "SandboxMode",
    "SandboxConfig",
    "SandboxPolicy",
    "detect_sandbox_mode",
    "init_sandbox",
    "get_sandbox_mode",
    "reset_sandbox_state",
    "policy_from_permission_rules",
    "wrap_command",
    "is_wrapper_failure",
]
