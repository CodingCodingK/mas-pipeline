## Purpose
Defines the core permission rule primitives — mode enum, rule parsing, glob matching, and the `PermissionChecker` class that evaluates deny-lists against tool invocations.
## Requirements
### Requirement: PermissionMode enum defines three operating modes
`PermissionMode` SHALL be a `str, Enum` with values: `BYPASS = "bypass"`, `NORMAL = "normal"`, `STRICT = "strict"`.

#### Scenario: Enum values
- **WHEN** PermissionMode members are accessed
- **THEN** `PermissionMode.BYPASS` SHALL equal `"bypass"`, `PermissionMode.NORMAL` SHALL equal `"normal"`, `PermissionMode.STRICT` SHALL equal `"strict"`

### Requirement: PermissionRule dataclass defines a single rule
`PermissionRule` SHALL be a dataclass with fields: `tool_name` (str), `pattern` (str | None), `action` (str: "allow" | "deny" | "ask").

#### Scenario: Rule with pattern
- **WHEN** `PermissionRule(tool_name="bash", pattern="git *", action="allow")` is created
- **THEN** it SHALL have tool_name="bash", pattern="git *", action="allow"

#### Scenario: Rule without pattern
- **WHEN** `PermissionRule(tool_name="shell", pattern=None, action="deny")` is created
- **THEN** it SHALL match all invocations of the "shell" tool

### Requirement: PermissionResult dataclass carries check outcome
`PermissionResult` SHALL be a dataclass with fields: `action` (str: "allow" | "deny" | "ask"), `reason` (str, default ""), `matched_rule` (PermissionRule | None, default None).

#### Scenario: Deny result with reason
- **WHEN** `PermissionResult(action="deny", reason="blocked by rule", matched_rule=rule)` is created
- **THEN** it SHALL carry the deny action, reason text, and the rule that triggered it

### Requirement: TOOL_CONTENT_FIELD maps tool names to their matchable parameter
`TOOL_CONTENT_FIELD` SHALL be a `dict[str, str]` mapping tool name to the parameter field name used for pattern matching. It SHALL contain at least: shell→command, write_file→file_path, write→file_path, read_file→file_path, edit→file_path, web_search→query.

#### Scenario: Known tool field lookup
- **WHEN** looking up "shell" in TOOL_CONTENT_FIELD
- **THEN** it SHALL return "command"

#### Scenario: write_file field lookup
- **WHEN** looking up "write_file" in TOOL_CONTENT_FIELD
- **THEN** it SHALL return "file_path"

#### Scenario: Unknown tool has no field
- **WHEN** looking up "spawn_agent" in TOOL_CONTENT_FIELD
- **THEN** it SHALL not be present (KeyError or .get returns None)

### Requirement: parse_rule parses rule string into PermissionRule
`parse_rule(rule_str, action)` SHALL parse a string like `"bash(git *)"` into `PermissionRule(tool_name="bash", pattern="git *", action=action)`. A string without parentheses like `"bash"` SHALL produce `PermissionRule(tool_name="bash", pattern=None, action=action)`.

#### Scenario: Rule with parenthesized pattern
- **WHEN** `parse_rule("write(/etc/*)", "deny")` is called
- **THEN** it SHALL return `PermissionRule(tool_name="write", pattern="/etc/*", action="deny")`

#### Scenario: Rule without pattern
- **WHEN** `parse_rule("shell", "deny")` is called
- **THEN** it SHALL return `PermissionRule(tool_name="shell", pattern=None, action="deny")`

#### Scenario: Rule with empty parentheses
- **WHEN** `parse_rule("bash()", "allow")` is called
- **THEN** it SHALL return `PermissionRule(tool_name="bash", pattern=None, action="allow")`

### Requirement: rule_matches checks if a rule applies to a tool call
`rule_matches(rule, tool_name, params)` SHALL return True if: (1) rule.tool_name equals tool_name, AND (2) either rule.pattern is None, or the tool's content field value matches rule.pattern via `fnmatch.fnmatch`.

#### Scenario: Tool name mismatch
- **WHEN** rule has tool_name="bash" and tool_name is "write"
- **THEN** rule_matches SHALL return False

#### Scenario: Tool name match, no pattern
- **WHEN** rule has tool_name="shell", pattern=None and tool_name is "shell"
- **THEN** rule_matches SHALL return True regardless of params

#### Scenario: Tool name match, pattern match
- **WHEN** rule has tool_name="bash", pattern="git *" and params={"command": "git status"}
- **THEN** rule_matches SHALL return True

#### Scenario: Tool name match, pattern no match
- **WHEN** rule has tool_name="bash", pattern="git *" and params={"command": "rm -rf /"}
- **THEN** rule_matches SHALL return False

#### Scenario: Tool not in TOOL_CONTENT_FIELD with pattern
- **WHEN** rule has tool_name="spawn_agent", pattern="researcher" and params={"role": "researcher"}
- **THEN** rule_matches SHALL return False (unknown tool ignores pattern, only tool_name match without pattern works)

### Requirement: check_permission evaluates rules with mode and priority
`check_permission(tool_name, params, rules, mode)` SHALL evaluate all matching rules and return a PermissionResult. Bypass mode SHALL skip all checks. Deny SHALL take priority over ask and allow. In strict mode, ask SHALL be converted to deny.

#### Scenario: Bypass mode skips all rules
- **WHEN** mode is BYPASS and rules contain deny rules matching the tool
- **THEN** check_permission SHALL return PermissionResult(action="allow")

#### Scenario: No matching rules defaults to allow
- **WHEN** no rules match the tool_name and params
- **THEN** check_permission SHALL return PermissionResult(action="allow")

#### Scenario: Deny takes priority over allow
- **WHEN** rules contain both `PermissionRule("bash", None, "allow")` and `PermissionRule("bash", "rm *", "deny")` and params={"command": "rm -rf /"}
- **THEN** check_permission SHALL return PermissionResult(action="deny")

#### Scenario: Ask in strict mode becomes deny
- **WHEN** mode is STRICT and the only matching rule has action="ask"
- **THEN** check_permission SHALL return PermissionResult(action="deny", reason contains "strict")

#### Scenario: Ask in normal mode returns ask
- **WHEN** mode is NORMAL and the only matching rule has action="ask"
- **THEN** check_permission SHALL return PermissionResult(action="ask")

#### Scenario: Multiple deny rules, first deny reason used
- **WHEN** multiple deny rules match
- **THEN** check_permission SHALL return deny with the first matching deny rule

### Requirement: load_permission_rules parses settings permissions config
`load_permission_rules(permissions_config)` SHALL parse a dict with optional keys "deny", "allow", "ask" (each a list of rule strings) into a `list[PermissionRule]`.

#### Scenario: Load mixed rules
- **GIVEN** config = {"deny": ["bash(rm *)"], "allow": ["read_file"], "ask": ["shell"]}
- **WHEN** load_permission_rules(config) is called
- **THEN** it SHALL return 3 PermissionRule objects with correct tool_name, pattern, and action

#### Scenario: Empty config
- **GIVEN** config = {}
- **WHEN** load_permission_rules(config) is called
- **THEN** it SHALL return an empty list

