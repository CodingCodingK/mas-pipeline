## ADDED Requirements

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
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool. The full pool SHALL be: read_file, shell, spawn_agent, web_search.

#### Scenario: get_all_tools includes web_search
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "web_search" mapped to a WebSearchTool instance

#### Scenario: Agent with web_search in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [web_search]
- **THEN** the agent's ToolRegistry SHALL contain WebSearchTool
