## Purpose
Wires the permission layer into the agent runtime: registers `PermissionChecker` as a `PRE_TOOL_USE` hook, threads deny rules from `Settings.permissions` into every agent build, and defines how sub-agents inherit parent rules.
## Requirements
### Requirement: register_permission_hooks registers Permission as PreToolUse hook
`register_permission_hooks(hook_runner, rules, mode)` SHALL register a callable hook on `PRE_TOOL_USE` that invokes `check_permission` and returns the appropriate `HookResult`.

#### Scenario: Deny rule triggers hook deny
- **WHEN** a registered permission hook runs for tool "bash" with params={"command": "rm -rf /"} and a deny rule matches
- **THEN** HookRunner.run SHALL return a HookResult with action="deny" and reason containing the rule info

#### Scenario: Allow result passes through
- **WHEN** a registered permission hook runs and check_permission returns allow
- **THEN** HookRunner.run SHALL return a HookResult with action="allow"

#### Scenario: Ask result with no responder falls back to deny
- **WHEN** a registered permission hook runs, check_permission returns ask, and no responder is registered
- **THEN** HookRunner.run SHALL return a HookResult with action="deny" and reason indicating no responder

#### Scenario: No rules registered means no hook
- **WHEN** register_permission_hooks is called with an empty rules list
- **THEN** no hook SHALL be registered on the HookRunner (zero overhead)

### Requirement: HookRunner supports callable executor type
HookRunner SHALL support a third executor type `"callable"` where `HookConfig.callable_fn` is an async function `(HookEvent) -> HookResult`. The runner SHALL call it directly instead of subprocess or LLM.

#### Scenario: Callable hook execution
- **WHEN** a hook with type="callable" and a callable_fn is registered and triggered
- **THEN** HookRunner SHALL call the callable_fn with the HookEvent and return its HookResult

#### Scenario: Callable hook timeout
- **WHEN** a callable hook takes longer than its timeout
- **THEN** HookRunner SHALL return HookResult(action="allow") (non-blocking, same as command/prompt)

### Requirement: SubAgent inherits parent deny rules
When SpawnAgentTool creates a sub-agent, it SHALL pass the parent agent's deny-only PermissionRules to the child agent via `parent_deny_rules`. The child's PermissionChecker SHALL merge parent deny rules with its own rules.

#### Scenario: Parent deny rule blocks child tool use
- **GIVEN** parent has deny rule `"bash(rm *)"` and child has no deny rules
- **WHEN** child agent attempts to call bash with command="rm -rf /"
- **THEN** the child's permission check SHALL deny the call

#### Scenario: Parent allow rule not inherited
- **GIVEN** parent has allow rule `"bash(git *)"` and child has no rules
- **WHEN** child agent attempts to call bash with command="git status"
- **THEN** the child's permission check SHALL allow (default allow when no rules match, NOT because of inherited allow)

#### Scenario: Child own deny rules still apply
- **GIVEN** parent has no deny rules and child has deny rule `"web_search"`
- **WHEN** child agent attempts to call web_search
- **THEN** the child's permission check SHALL deny the call

### Requirement: PermissionChecker class encapsulates rules + mode for an agent
`PermissionChecker(rules, mode, parent_deny_rules)` SHALL merge parent_deny_rules into its rule set and provide a `check(tool_name, params)` method that calls `check_permission`.

#### Scenario: Check delegates to check_permission
- **WHEN** checker.check("bash", {"command": "ls"}) is called
- **THEN** it SHALL call check_permission with the merged rules and configured mode

#### Scenario: Extract deny rules for child
- **WHEN** checker.get_deny_rules() is called
- **THEN** it SHALL return all rules with action="deny" (own + inherited)

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

