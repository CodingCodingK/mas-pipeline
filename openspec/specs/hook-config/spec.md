## ADDED Requirements

### Requirement: Load hooks from settings.yaml
The system SHALL load hook configurations from the `hooks` section of settings.yaml. Each entry maps an event type to a list of hook matchers, each containing a list of hook definitions.

#### Scenario: Settings.yaml hook configuration
- **WHEN** settings.yaml contains:
  ```yaml
  hooks:
    pre_tool_use:
      - matcher: "shell"
        hooks:
          - type: command
            command: "python scripts/validate_shell.py"
            timeout: 10
  ```
- **THEN** HookRunner SHALL have one command hook registered for PRE_TOOL_USE matching "shell"

#### Scenario: No hooks section in settings
- **WHEN** settings.yaml has no `hooks` section
- **THEN** HookRunner SHALL have zero hooks registered (empty, not error)

#### Scenario: Multiple hooks for same event
- **WHEN** settings.yaml has two matcher entries under `pre_tool_use`
- **THEN** both SHALL be registered and both SHALL be evaluated when a PreToolUse event fires

### Requirement: Load hooks from agent frontmatter
The system SHALL load hook configurations from the optional `hooks` field in agent .md frontmatter. These hooks are role-specific and are registered when create_agent builds the HookRunner for that agent.

#### Scenario: Agent frontmatter hook
- **WHEN** agents/researcher.md has frontmatter:
  ```yaml
  hooks:
    pre_tool_use:
      - matcher: "shell"
        hooks:
          - type: command
            command: "exit 2"
  ```
- **THEN** the researcher agent's HookRunner SHALL deny all shell tool calls

#### Scenario: Agent without hooks frontmatter
- **WHEN** an agent .md file has no `hooks` field in frontmatter
- **THEN** only global hooks from settings.yaml SHALL apply

### Requirement: Hook configuration schema
Each hook definition SHALL have: `type` (str: "command" or "prompt", required), `command` (str, required for command type), `prompt` (str, required for prompt type), `timeout` (int, optional, default 30 seconds), `matcher` (str, optional).

#### Scenario: Command hook config
- **WHEN** a hook config has type="command" and command="python validate.py"
- **THEN** it SHALL be valid

#### Scenario: Prompt hook config
- **WHEN** a hook config has type="prompt" and prompt="Is this safe? $ARGUMENTS"
- **THEN** it SHALL be valid

#### Scenario: Invalid hook type
- **WHEN** a hook config has type="http"
- **THEN** it SHALL be rejected with a validation error at load time

#### Scenario: Missing required field
- **WHEN** a hook config has type="command" but no command field
- **THEN** it SHALL be rejected with a validation error at load time

### Requirement: Global hooks merge with agent hooks
When building a HookRunner for an agent, global hooks from settings.yaml SHALL be loaded first, then agent-specific hooks from frontmatter SHALL be appended. Agent hooks do NOT override global hooks; both run.

#### Scenario: Global and agent hooks both fire
- **WHEN** settings.yaml has a PreToolUse hook for "shell" and agents/writer.md also has a PreToolUse hook for "shell"
- **THEN** both hooks SHALL execute when the writer agent calls shell
