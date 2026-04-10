## ADDED Requirements

### Requirement: ShellTool sandbox wrapping
`ShellTool.call()` SHALL, before invoking `subprocess.run` (or `asyncio.create_subprocess_exec`), call `wrap_command(argv, mode, policy)` where:
- `mode` is the cached `SandboxMode` produced by `init_sandbox()` at startup
- `policy` is `policy_from_permission_rules(active_rules)` computed for the current call's permission context

The wrapped argv SHALL be used for the actual subprocess execution. ShellTool SHALL NOT call any sandbox primitive directly; all platform branching lives inside `wrap_command`.

#### Scenario: Linux ShellTool execution wraps with bwrap
- **WHEN** `ShellTool.call({"command": "ls projects"})` is invoked on Linux with bwrap available
- **THEN** the subprocess argv SHALL begin with `bwrap` and the ShellTool SHALL NOT have called `bwrap` itself outside `wrap_command`

#### Scenario: Windows ShellTool execution unchanged
- **WHEN** `ShellTool.call({"command": "ls projects"})` is invoked on Windows
- **THEN** the subprocess argv SHALL be identical to the unwrapped command (passthrough)

#### Scenario: Disabled sandbox short-circuits wrapping cost
- **WHEN** the active mode is `DISABLED`
- **THEN** ShellTool SHALL still call `wrap_command`, which SHALL return the unmodified argv

### Requirement: Wrapper failure surfaced in ToolResult metadata
When the wrapped subprocess exits non-zero and `is_wrapper_failure(stderr, exit_code)` returns True, ShellTool SHALL set `metadata["wrapper_failure"] = True` and `metadata["sandbox_mode"] = <mode value>` on the returned `ToolResult`. The `output` field SHALL include both the wrapper stderr and a hint that the failure originated in the sandbox layer, not the user command.

#### Scenario: bwrap setup error tagged
- **WHEN** the wrapped subprocess returns exit code 1 with stderr `bwrap: Can't bind /missing: No such file`
- **THEN** the ToolResult SHALL have `success=False`, `metadata["wrapper_failure"]=True`, and the output SHALL contain the bwrap stderr line

#### Scenario: Real command failure not tagged
- **WHEN** the wrapped subprocess returns exit code 2 with stderr `ls: cannot access /nope`
- **THEN** the ToolResult SHALL have `metadata["wrapper_failure"]=False` (or the key absent)

### Requirement: Per-call sandbox escape hatch
`ShellTool.call()` SHALL accept an optional `dangerously_disable_sandbox: bool` parameter (default `False`). When True, ShellTool SHALL bypass `wrap_command` and execute the raw argv. Using this parameter SHALL trigger a `PreToolUse` permission ask in NORMAL and STRICT permission modes; ALLOW mode SHALL permit it without prompting.

#### Scenario: Default value wraps normally
- **WHEN** `ShellTool.call({"command": "ls"})` is invoked without `dangerously_disable_sandbox`
- **THEN** the command SHALL be wrapped via `wrap_command`

#### Scenario: Escape hatch bypasses wrapper
- **WHEN** `ShellTool.call({"command": "apt install curl", "dangerously_disable_sandbox": True})` is invoked and Permission allows it
- **THEN** the subprocess argv SHALL be the raw command, not a bwrap-prefixed one

#### Scenario: Escape hatch requires permission ask in NORMAL mode
- **WHEN** `dangerously_disable_sandbox=True` is passed in NORMAL permission mode
- **THEN** the PreToolUse hook SHALL prompt the user before execution
