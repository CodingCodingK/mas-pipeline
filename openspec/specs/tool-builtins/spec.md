## Purpose
Defines the built-in tool implementations: read_file, shell, spawn_agent, web_search, memory_read/write, search_docs, plus the global tool pool helper.
## Requirements
### Requirement: read_file tool
The system SHALL provide a `ReadFileTool` that reads file contents from the local filesystem.
- `name`: "read_file"
- `input_schema`: `{"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}`
  - `file_path` is required; `offset` and `limit` are optional
- `is_concurrency_safe`: always `True` (hardcoded, pure read operation)
- `is_read_only`: always `True`

#### Scenario: Read entire file
- **WHEN** `read_file` is called with `{"file_path": "/path/to/file.py"}`
- **THEN** it SHALL return `ToolResult(output=<file contents with line numbers>, success=True)`

#### Scenario: Read file with offset and limit
- **WHEN** `read_file` is called with `{"file_path": "/path/to/file.py", "offset": 10, "limit": 20}`
- **THEN** it SHALL return lines 10-29 of the file with line numbers

#### Scenario: File not found
- **WHEN** `read_file` is called with a non-existent file path
- **THEN** it SHALL return `ToolResult(output="Error: file not found: /path/to/file.py", success=False)`

#### Scenario: Output truncation
- **WHEN** file content exceeds 30000 characters
- **THEN** output SHALL be truncated to 30000 characters with a `[truncated]` marker appended

### Requirement: shell tool
The system SHALL provide a `ShellTool` that executes shell commands.
- `name`: "shell"
- `input_schema`: `{"command": {"type": "string"}, "timeout": {"type": "integer"}}`
  - `command` is required; `timeout` is optional (default 120 seconds)
- `is_concurrency_safe`: dynamic, based on command content analysis
- `is_read_only`: equals `is_concurrency_safe` in Phase 1

#### Scenario: Execute simple command
- **WHEN** `shell` is called with `{"command": "ls -la src/"}`
- **THEN** it SHALL return `ToolResult(output=<stdout>, success=True, metadata={"exit_code": 0})`

#### Scenario: Command fails with non-zero exit code
- **WHEN** `shell` is called with a command that exits non-zero
- **THEN** it SHALL return `ToolResult(output=<stdout + stderr>, success=False, metadata={"exit_code": <code>})`

#### Scenario: Command timeout
- **WHEN** a command exceeds the timeout (default 120s)
- **THEN** the process SHALL be killed and return `ToolResult(output="Error: command timed out after 120s", success=False)`

#### Scenario: Output truncation
- **WHEN** command output exceeds 30000 characters
- **THEN** output SHALL be truncated to 30000 characters with a `[truncated]` marker appended

### Requirement: shell concurrency safety detection
The `ShellTool.is_concurrency_safe(params)` SHALL determine safety by:
1. If command contains `$`, backtick, or `>` → return `False`
2. Split command by separators (`&&`, `||`, `;`, `|`) into subcommands
3. Each subcommand MUST match a prefix in SAFE_PREFIXES to be considered safe
4. Return `True` only if ALL subcommands match; otherwise `False`

SAFE_PREFIXES SHALL include at minimum: `cat `, `ls `, `head `, `tail `, `wc `, `find `, `grep `, `rg `, `git log`, `git status`, `git diff`, `git show`, `git branch`, `git tag`, `pwd`, `echo `, `which `, `type `, `file `, `python --version`, `node --version`.

#### Scenario: Simple safe command
- **WHEN** `is_concurrency_safe({"command": "git log --oneline"})` is called
- **THEN** it SHALL return `True`

#### Scenario: Pipe of safe commands
- **WHEN** `is_concurrency_safe({"command": "git log | head -20"})` is called
- **THEN** it SHALL return `True` (both subcommands match SAFE_PREFIXES)

#### Scenario: Variable expansion detected
- **WHEN** `is_concurrency_safe({"command": "echo $HOME"})` is called
- **THEN** it SHALL return `False`

#### Scenario: Unknown command defaults to unsafe
- **WHEN** `is_concurrency_safe({"command": "python script.py"})` is called
- **THEN** it SHALL return `False` (no matching prefix)

### Requirement: shell working directory persistence
The `ShellTool` SHALL maintain a `_cwd` state that persists across invocations.
- Initial value: project root directory
- After each command execution, the tool SHALL query the resulting working directory and update `_cwd`
- Subsequent commands SHALL execute in the updated `_cwd`

#### Scenario: cd persists across calls
- **WHEN** `shell({"command": "cd /tmp"})` is called, followed by `shell({"command": "pwd"})`
- **THEN** the second call SHALL output `/tmp`

#### Scenario: Initial working directory
- **WHEN** `shell` is first called without any prior cd
- **THEN** the command SHALL execute in the project root directory

### Requirement: Global tool pool includes web_search
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool, MemoryReadTool, MemoryWriteTool, SearchDocsTool, and WriteFileTool. The full pool SHALL be: read_file, write_file, shell, spawn_agent, web_search, memory_read, memory_write, search_docs.

#### Scenario: get_all_tools includes web_search
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "web_search" mapped to a WebSearchTool instance

#### Scenario: get_all_tools includes memory tools
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain keys "memory_read" and "memory_write" mapped to their respective tool instances

#### Scenario: get_all_tools includes search_docs
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "search_docs" mapped to a SearchDocsTool instance

#### Scenario: get_all_tools includes write_file
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "write_file" mapped to a WriteFileTool instance

#### Scenario: Total tool count
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL have exactly 8 entries

#### Scenario: Agent with web_search in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [web_search]
- **THEN** the agent's ToolRegistry SHALL contain WebSearchTool

#### Scenario: Agent with memory tools in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [memory_read, memory_write]
- **THEN** the agent's ToolRegistry SHALL contain both MemoryReadTool and MemoryWriteTool

#### Scenario: Agent with write_file in role whitelist
- **GIVEN** agents/writer.md has tools: [read_file, write_file]
- **WHEN** create_agent is called for role writer
- **THEN** the agent's ToolRegistry SHALL contain WriteFileTool

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

### Requirement: writer / assistant / general roles have write_file in their tool frontmatter
The role files `agents/writer.md`, `agents/assistant.md`, and `agents/general.md` SHALL each include `write_file` in their `tools:` frontmatter list. Other pipeline worker roles (analyzer, exam_generator, exam_reviewer, reviewer, parser, coordinator, researcher) SHALL NOT have `write_file` in their tools list.

#### Scenario: Writer role has write_file
- **WHEN** `agents/writer.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: Assistant role has write_file
- **WHEN** `agents/assistant.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: General role has write_file
- **WHEN** `agents/general.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: Parser role does not have write_file
- **WHEN** `agents/parser.md` frontmatter is parsed
- **THEN** its `tools` list SHALL NOT contain `"write_file"`

