## ADDED Requirements

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
`Settings` model SHALL include a `permissions` field (dict, default {}) for permission rule configuration.

#### Scenario: Settings with permissions
- **GIVEN** settings.yaml contains `permissions: {deny: ["bash(rm *)"]}`
- **WHEN** Settings is loaded
- **THEN** settings.permissions SHALL be `{"deny": ["bash(rm *)"]}`

#### Scenario: Settings without permissions
- **GIVEN** settings.yaml has no `permissions` key
- **WHEN** Settings is loaded
- **THEN** settings.permissions SHALL be `{}`
