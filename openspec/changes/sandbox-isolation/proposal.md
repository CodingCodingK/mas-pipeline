## Why

Permission rules pattern-match strings before tool calls, so they can be evaded by symlink, cwd tricks, or shell expansion. We need a kernel-level last line of defense for ShellTool that confines commands to a smaller filesystem and network world, regardless of what string the agent constructed. CC ships exactly this layer (bubblewrap on Linux, sandbox-exec on macOS, per-call wrap), and we adopt the same model — no Docker, no in-house enforcement.

## What Changes

- Add a `src/sandbox/` package (~200 lines) that, on each ShellTool call, wraps the command with `bwrap` (Linux) or `sandbox-exec` (macOS), or passes through with a one-time warning (Windows).
- Detect sandbox availability at startup; choose mode (`linux-bwrap` / `macos-sbx` / `passthrough`); print mode in the boot banner.
- Translate Permission rules (the source of truth) into sandbox allow/deny path lists at wrap time, so what Permission allows is exactly what the sandbox makes writable.
- Add `sandbox.enabled` (default `true`) and `sandbox.fail_if_unavailable` (default `false`) to `config/settings.yaml`.
- Modify ShellTool to call `wrap_command()` before `subprocess.run`. No other tools change — file tools (Read/Write) execute inside the Python process and bwrap cannot see them.
- Network is fully disabled inside the sandbox. Tools that legitimately need network (WebSearch, MCP) already run in the parent Python process and bypass it.
- **Non-goals (explicitly cut)**: Docker backend, per-domain network whitelist / egress proxy, Windows-native sandbox (AppContainer), CPU/memory limits, violations dashboard.

## Capabilities

### New Capabilities
- `sandbox-detection`: Startup detection of platform + binary availability, mode selection, warn-or-fail behavior, memoized result.
- `sandbox-wrapper`: The `wrap_command(cmd, config) -> list[str]` interface and its three platform branches (bwrap / sandbox-exec / passthrough).
- `sandbox-permission-sync`: Conversion from `PermissionRule` entries into sandbox allow/deny path lists, so Permission stays the single source of truth.

### Modified Capabilities
- `tool-builtins`: ShellTool gains a sandbox-wrap step before subprocess execution, governed by the active sandbox mode.

## Impact

- New code: `src/sandbox/{types,detector,wrapper,sync}.py`, plus init hook called from app startup.
- Modified code: `src/tools/builtins/shell.py` (1 wrap call), `src/config.py` (new section), startup banner.
- Operational: Linux deployments need `apt install bubblewrap`; if missing the system warns and runs commands raw (configurable to hard-fail).
- CI: Linux runners install bubblewrap; macOS runners use system `sandbox-exec`; Windows CI skips sandbox tests via `skipif`.
- Dev experience: Junjie's primary box is Windows — sandbox is a no-op there with one-time warning, so no friction.
- No spec breakage; ShellTool's external contract (input/output/errors) is unchanged when the wrapped command succeeds. Wrapped failures bubble up the underlying exit code.
