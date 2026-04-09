## ADDED Requirements

### Requirement: HookRunner manages hook registration and execution
HookRunner SHALL be a class that stores registered hooks and executes matching hooks for a given event. It SHALL provide methods: `register(event_type, hook_config)`, `run(event: HookEvent) -> HookResult`.

#### Scenario: Register and run a hook
- **WHEN** a command hook is registered for PRE_TOOL_USE and a PreToolUse event fires
- **THEN** HookRunner.run() SHALL execute the hook and return the aggregated HookResult

#### Scenario: No hooks registered for event
- **WHEN** HookRunner.run() is called for an event with no registered hooks
- **THEN** it SHALL return HookResult(action="allow") immediately

#### Scenario: Multiple hooks for same event
- **WHEN** three hooks are registered for POST_TOOL_USE and a PostToolUse event fires
- **THEN** all three SHALL execute in parallel and results SHALL be aggregated

### Requirement: Matcher filters hooks by tool name
Each hook registration MAY include a `matcher` pattern (str). For tool events (PreToolUse, PostToolUse, PostToolUseFailure), the matcher SHALL be compared against the tool_name in the event payload. If matcher is None or empty, the hook matches all tools. Matcher SHALL support `|`-separated alternatives (e.g., "shell|read_file").

#### Scenario: Matcher matches specific tool
- **WHEN** a hook is registered with matcher="shell" and a PreToolUse event fires for tool_name="shell"
- **THEN** the hook SHALL execute

#### Scenario: Matcher does not match
- **WHEN** a hook is registered with matcher="shell" and a PreToolUse event fires for tool_name="read_file"
- **THEN** the hook SHALL NOT execute

#### Scenario: Matcher with alternatives
- **WHEN** a hook is registered with matcher="shell|spawn_agent" and a PreToolUse event fires for tool_name="spawn_agent"
- **THEN** the hook SHALL execute

#### Scenario: No matcher matches all
- **WHEN** a hook is registered with matcher=None
- **THEN** the hook SHALL execute for all tool events

### Requirement: Command hook executor
Command hooks SHALL spawn a subprocess, write the HookEvent payload as JSON to stdin, and read the result from stdout. The subprocess SHALL be spawned with a configurable timeout (default 30 seconds).

#### Scenario: Command hook succeeds
- **WHEN** a command hook runs `python validate.py`, the subprocess receives JSON on stdin, and exits with code 0 and JSON stdout
- **THEN** HookRunner SHALL parse stdout as HookResult fields

#### Scenario: Command hook blocks (exit code 2)
- **WHEN** a command hook exits with code 2 and stderr="forbidden operation"
- **THEN** HookResult SHALL have action="deny" and reason containing the stderr message

#### Scenario: Command hook exit code 0 with no JSON output
- **WHEN** a command hook exits with code 0 and stdout is empty or non-JSON
- **THEN** HookResult SHALL be action="allow"

#### Scenario: Command hook non-blocking error (exit code != 0 and != 2)
- **WHEN** a command hook exits with code 1
- **THEN** HookResult SHALL be action="allow" (non-blocking) and the error SHALL be logged

#### Scenario: Command hook timeout
- **WHEN** a command hook does not exit within the configured timeout
- **THEN** the process SHALL be killed and HookResult SHALL be action="allow" (non-blocking timeout)

### Requirement: Prompt hook executor
Prompt hooks SHALL call the LLM (light tier) with a prompt template where `$ARGUMENTS` is replaced by the HookEvent payload JSON. The LLM response SHALL be parsed as a HookResult.

#### Scenario: Prompt hook evaluates tool call
- **WHEN** a prompt hook has template "Is this shell command safe? $ARGUMENTS" and a PreToolUse event fires
- **THEN** `$ARGUMENTS` SHALL be replaced with the event payload JSON and the light model SHALL be called

#### Scenario: Prompt hook returns deny
- **WHEN** the LLM responds with JSON containing action="deny" and reason="unsafe command"
- **THEN** HookResult SHALL have action="deny" and reason="unsafe command"

#### Scenario: Prompt hook LLM error
- **WHEN** the LLM call fails with an exception
- **THEN** HookResult SHALL be action="allow" (non-blocking) and the error SHALL be logged

### Requirement: Hook execution is parallel with per-hook timeout
All matching hooks for an event SHALL execute concurrently via asyncio.gather. Each hook has its own timeout. A failing hook SHALL NOT block other hooks from completing.

#### Scenario: Parallel execution
- **WHEN** three hooks match an event
- **THEN** all three SHALL start concurrently (not sequentially)

#### Scenario: One hook fails, others succeed
- **WHEN** hook A times out and hooks B and C succeed
- **THEN** results from B and C SHALL be aggregated, hook A's failure SHALL be logged

### Requirement: HookRunner is injectable into ToolOrchestrator
HookRunner SHALL be passed to ToolOrchestrator at construction time. If no HookRunner is provided, the orchestrator SHALL skip hook execution (backward compatible).

#### Scenario: Orchestrator with hooks
- **WHEN** ToolOrchestrator is created with a HookRunner
- **THEN** it SHALL call hooks before and after tool execution

#### Scenario: Orchestrator without hooks
- **WHEN** ToolOrchestrator is created without a HookRunner (None)
- **THEN** tool execution SHALL proceed as before with no hook calls
