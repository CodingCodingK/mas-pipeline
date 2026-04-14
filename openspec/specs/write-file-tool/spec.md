# write-file-tool Specification

## Purpose
TBD - created by archiving change activate-permission-and-mcp-github. Update Purpose after archive.
## Requirements
### Requirement: WriteFileTool writes text content to a file path
The system SHALL provide a `WriteFileTool` (`src/tools/builtins/write_file.py`) that writes text content to a file on the local filesystem.
- `name`: "write_file"
- `input_schema`:
  - `file_path` (string, required) — target path
  - `content` (string, required) — text to write
  - `append` (boolean, optional, default `false`) — when `true`, append to existing file instead of overwriting
  - `encoding` (string, optional, default `"utf-8"`) — text encoding
- `is_concurrency_safe`: always `False` (write operation)
- `is_read_only`: always `False`

#### Scenario: Write new file
- **WHEN** `write_file` is called with `{"file_path": "projects/1/outputs/a.txt", "content": "hello"}`
- **THEN** it SHALL create the file (and any missing parent directories) and return `ToolResult(output="Wrote 5 bytes to projects/1/outputs/a.txt", success=True)`

#### Scenario: Overwrite existing file
- **WHEN** `write_file` is called with an existing file path and `append=false` (default)
- **THEN** the file contents SHALL be replaced entirely with the new content

#### Scenario: Append mode
- **WHEN** `write_file` is called with `append=true` on an existing file
- **THEN** the new content SHALL be appended to the end of the file without truncating existing content

#### Scenario: Parent directory is created automatically
- **WHEN** `write_file` is called with a `file_path` whose parent directory does not exist
- **THEN** the parent directories SHALL be created via `mkdir -p` semantics before writing

### Requirement: WriteFileTool normalizes paths before permission check
`WriteFileTool` SHALL resolve `file_path` to an absolute canonical path via `os.path.realpath` **before** the permission layer sees the argument, so that path-escape attempts like `./src/../src/foo.py` or `projects/../src/foo.py` are matched against their real destination.

#### Scenario: Relative traversal is normalized
- **GIVEN** a deny rule `write_file(src/**)`
- **WHEN** `write_file` is called with `file_path="projects/../src/exploit.py"`
- **THEN** the permission check SHALL see a normalized path that matches `src/**` and SHALL deny the call

#### Scenario: Symlink following during normalization
- **WHEN** `file_path` contains a symlink to a protected directory
- **THEN** `realpath` SHALL resolve the symlink and the permission check SHALL match against the real target

### Requirement: WriteFileTool errors surface as non-successful ToolResult
On IO errors (permission denied at OS level, disk full, invalid encoding), `WriteFileTool` SHALL return a `ToolResult(success=False, output="Error: <reason>")` instead of raising — consistent with `ReadFileTool` error semantics.

#### Scenario: OS-level permission denied
- **WHEN** `write_file` is called with a path the process has no write permission to
- **THEN** the tool SHALL return `ToolResult(success=False)` with an error message containing "permission denied" or the OS error string

### Requirement: WriteFileTool is registered in the global tool pool
`get_all_tools()` SHALL include `WriteFileTool()` in its returned dict under key `"write_file"`.

#### Scenario: write_file available via get_all_tools
- **WHEN** `get_all_tools()` is called
- **THEN** the returned dict SHALL contain a key `"write_file"` mapped to a `WriteFileTool` instance

