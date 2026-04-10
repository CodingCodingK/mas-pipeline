"""Sandbox types: SandboxMode enum, SandboxConfig (pydantic), SandboxPolicy (dataclass)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel


class SandboxMode(str, Enum):
    """Active sandbox backend selected at startup.

    LINUX_BWRAP   — bubblewrap available, commands wrapped via bwrap
    MACOS_SBX     — macOS sandbox-exec available
    PASSTHROUGH   — platform unsupported or binary missing; commands run raw
    DISABLED      — user disabled sandbox via config; commands run raw
    """

    LINUX_BWRAP = "linux-bwrap"
    MACOS_SBX = "macos-sbx"
    PASSTHROUGH = "passthrough"
    DISABLED = "disabled"


class SandboxConfig(BaseModel):
    """Sandbox section of settings.yaml."""

    enabled: bool = True
    fail_if_unavailable: bool = False


@dataclass
class SandboxPolicy:
    """Per-call policy: which paths are writable / readable, whether network is allowed."""

    writable_paths: list[str] = field(default_factory=list)
    readonly_paths: list[str] = field(default_factory=list)
    allow_network: bool = False
