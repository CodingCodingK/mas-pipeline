## MODIFIED Requirements

### Requirement: Settings permissions config field
`Settings` model SHALL include a `permissions` field (dict, default {}) for permission rule configuration. The shipped `config/settings.yaml` SHALL populate this field with a non-empty deny-only ruleset that protects the following path classes (via `write_file(<glob>)` rules): `agents/**`, `src/**`, `config/**`, `openspec/**`, `.plan/**`, `pipelines/**`, `skills/**`, `.git/**`, `.env*`, `.claude/**`. It SHALL additionally deny the following shell patterns (via `shell(<glob>)` rules): `rm -rf *`, `sudo *`, `curl *|*sh*`, `git push *`, `* > /etc/*`.

#### Scenario: Settings with permissions
- **GIVEN** settings.yaml contains `permissions: {deny: ["bash(rm *)"]}`
- **WHEN** Settings is loaded
- **THEN** settings.permissions SHALL be `{"deny": ["bash(rm *)"]}`

#### Scenario: Settings without permissions
- **GIVEN** settings.yaml has no `permissions` key
- **WHEN** Settings is loaded
- **THEN** settings.permissions SHALL be `{}`

#### Scenario: Shipped settings.yaml contains write_file path denies
- **WHEN** `config/settings.yaml` is loaded via `get_settings()` with no local overrides
- **THEN** `settings.permissions["deny"]` SHALL be a list containing every protected path class, each formatted as `write_file(<glob>)`
- **AND** the list SHALL contain `"write_file(src/**)"`, `"write_file(config/**)"`, `"write_file(.env*)"`

#### Scenario: Shipped settings.yaml contains shell command denies
- **WHEN** `config/settings.yaml` is loaded via `get_settings()` with no local overrides
- **THEN** `settings.permissions["deny"]` SHALL contain the string `"shell(rm -rf *)"`
- **AND** SHALL contain `"shell(sudo *)"`

## ADDED Requirements

### Requirement: Deny rules fire for write_file calls targeting protected paths
Given the shipped `config/settings.yaml` permission deny list, when any agent (NORMAL mode) calls `write_file` with a `file_path` that matches one of the protected globs after `realpath` normalization, the PreToolUse hook SHALL return `HookResult(action="deny")` and the tool invocation SHALL be blocked before reaching the tool's `run()` method.

#### Scenario: Write to src is denied
- **GIVEN** assistant agent is running in NORMAL mode with shipped permission rules
- **WHEN** the agent attempts `write_file(file_path="src/foo.py", content="x")`
- **THEN** the PreToolUse hook SHALL return deny
- **AND** the tool result returned to the LLM SHALL be an error ToolResult containing `"permission_denied"` or the deny reason
- **AND** telemetry SHALL record a permission_denied event for this invocation

#### Scenario: Write to projects outputs is allowed
- **GIVEN** same configuration
- **WHEN** the agent attempts `write_file(file_path="projects/1/outputs/draft.md", content="x")`
- **THEN** no deny rule SHALL match
- **AND** the write SHALL succeed

#### Scenario: Dangerous shell command is denied
- **GIVEN** same configuration
- **WHEN** any agent attempts `shell(command="rm -rf /tmp/x")`
- **THEN** the PreToolUse hook SHALL return deny because `rm -rf *` glob matches the command string
