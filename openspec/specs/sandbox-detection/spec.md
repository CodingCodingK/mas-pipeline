# sandbox-detection Specification

## Purpose
TBD - created by archiving change sandbox-isolation. Update Purpose after archive.
## Requirements
### Requirement: SandboxMode enum
The system SHALL define a `SandboxMode` enum in `src/sandbox/types.py` with exactly four values: `LINUX_BWRAP`, `MACOS_SBX`, `PASSTHROUGH`, `DISABLED`. `DISABLED` indicates the user turned sandbox off in config; `PASSTHROUGH` indicates the platform has no supported backend or the binary is missing and `fail_if_unavailable` is false.

#### Scenario: Enum has four members
- **WHEN** importing `SandboxMode` from `src.sandbox.types`
- **THEN** the enum SHALL have exactly the members `LINUX_BWRAP`, `MACOS_SBX`, `PASSTHROUGH`, `DISABLED`

### Requirement: SandboxConfig dataclass
The system SHALL define a `SandboxConfig` dataclass in `src/sandbox/types.py` with fields: `enabled: bool` (default `True`), `fail_if_unavailable: bool` (default `False`). It SHALL be loaded from the `sandbox` section of `config/settings.yaml` and exposed via the existing config loader.

#### Scenario: Defaults applied when section missing
- **WHEN** `config/settings.yaml` has no `sandbox` section
- **THEN** `SandboxConfig()` SHALL be constructed with `enabled=True` and `fail_if_unavailable=False`

#### Scenario: Values loaded from settings
- **WHEN** `config/settings.yaml` contains `sandbox: { enabled: false }`
- **THEN** the loaded `SandboxConfig` SHALL have `enabled=False`

### Requirement: detect_sandbox_mode function
The system SHALL provide `detect_sandbox_mode(config: SandboxConfig) -> SandboxMode` in `src/sandbox/detector.py`. The function SHALL:
1. Return `DISABLED` if `config.enabled` is False.
2. On Linux (including WSL2), return `LINUX_BWRAP` if `bwrap` is found on `PATH`.
3. On macOS, return `MACOS_SBX` if `/usr/bin/sandbox-exec` exists.
4. Otherwise, raise `RuntimeError` if `config.fail_if_unavailable` is True; else return `PASSTHROUGH`.

The result SHALL be memoized so subsequent calls do not re-probe `PATH`.

#### Scenario: Linux with bwrap installed
- **WHEN** `detect_sandbox_mode` runs on Linux and `which bwrap` succeeds
- **THEN** it SHALL return `SandboxMode.LINUX_BWRAP`

#### Scenario: macOS always has sandbox-exec
- **WHEN** `detect_sandbox_mode` runs on macOS
- **THEN** it SHALL return `SandboxMode.MACOS_SBX`

#### Scenario: Windows passthrough
- **WHEN** `detect_sandbox_mode` runs on Windows with default config
- **THEN** it SHALL return `SandboxMode.PASSTHROUGH`

#### Scenario: Hard fail when binary missing and configured strict
- **WHEN** `detect_sandbox_mode` runs on Linux without bwrap and `fail_if_unavailable=True`
- **THEN** it SHALL raise `RuntimeError` with a message naming the missing binary

#### Scenario: Disabled by config
- **WHEN** `detect_sandbox_mode` runs with `config.enabled=False`
- **THEN** it SHALL return `SandboxMode.DISABLED` regardless of platform

#### Scenario: Result memoized
- **WHEN** `detect_sandbox_mode` is called twice with the same config
- **THEN** the underlying `which`/`exists` probes SHALL run only once

### Requirement: init_sandbox boot banner
The application startup SHALL call `init_sandbox()` once, which invokes `detect_sandbox_mode` and logs a single human-readable line at INFO level naming the selected mode (e.g. `sandbox: linux-bwrap` or `sandbox: passthrough (warn: bubblewrap not installed)`).

#### Scenario: Banner printed at startup
- **WHEN** the application boots with sandbox configured
- **THEN** stderr/log SHALL contain exactly one `sandbox:` line indicating the active mode

#### Scenario: Passthrough warns once, not per call
- **WHEN** `init_sandbox` selects `PASSTHROUGH` due to a missing binary
- **THEN** the warning SHALL be emitted exactly once at boot, not on each ShellTool call

