"""Sandbox detection: pick a SandboxMode based on platform + binary availability.

Result is memoized — `init_sandbox()` resolves it once at boot, subsequent
`get_sandbox_mode()` calls return the cached value.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil

from src.sandbox.types import SandboxConfig, SandboxMode

logger = logging.getLogger(__name__)

_cached_mode: SandboxMode | None = None
_warned_passthrough: bool = False


def detect_sandbox_mode(config: SandboxConfig) -> SandboxMode:
    """Resolve the sandbox mode for the current platform + config.

    Raises RuntimeError if `fail_if_unavailable=True` and the platform's
    sandbox binary is missing.
    """
    if not config.enabled:
        return SandboxMode.DISABLED

    system = platform.system()

    if system == "Linux":
        if shutil.which("bwrap"):
            return SandboxMode.LINUX_BWRAP
        if config.fail_if_unavailable:
            raise RuntimeError(
                "sandbox: bubblewrap (bwrap) not found on PATH and "
                "fail_if_unavailable=true. Install with: apt install bubblewrap"
            )
        return SandboxMode.PASSTHROUGH

    if system == "Darwin":
        if os.path.exists("/usr/bin/sandbox-exec"):
            return SandboxMode.MACOS_SBX
        if config.fail_if_unavailable:
            raise RuntimeError(
                "sandbox: /usr/bin/sandbox-exec missing and fail_if_unavailable=true."
            )
        return SandboxMode.PASSTHROUGH

    # Windows or anything else: no native primitive
    if config.fail_if_unavailable:
        raise RuntimeError(
            f"sandbox: no supported backend for platform {system!r} "
            "and fail_if_unavailable=true."
        )
    return SandboxMode.PASSTHROUGH


def init_sandbox(config: SandboxConfig | None = None) -> SandboxMode:
    """Resolve and cache the sandbox mode. Logs one banner line.

    Safe to call multiple times — only the first call probes the system.
    """
    global _cached_mode, _warned_passthrough

    if _cached_mode is not None:
        return _cached_mode

    if config is None:
        config = SandboxConfig()

    mode = detect_sandbox_mode(config)
    _cached_mode = mode

    if mode == SandboxMode.PASSTHROUGH:
        system = platform.system()
        reason = (
            "bubblewrap not installed"
            if system == "Linux"
            else "sandbox-exec missing"
            if system == "Darwin"
            else f"unsupported platform ({system})"
        )
        logger.warning("sandbox: passthrough (warn: %s)", reason)
        _warned_passthrough = True
    else:
        logger.info("sandbox: %s", mode.value)

    return mode


def get_sandbox_mode() -> SandboxMode:
    """Return the cached mode. Calls `init_sandbox()` if not yet initialized."""
    if _cached_mode is None:
        return init_sandbox()
    return _cached_mode


def reset_sandbox_state() -> None:
    """Test-only: clear the memoized mode and warning flag."""
    global _cached_mode, _warned_passthrough
    _cached_mode = None
    _warned_passthrough = False
