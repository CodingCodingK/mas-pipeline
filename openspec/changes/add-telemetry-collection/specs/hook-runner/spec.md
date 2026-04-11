## ADDED Requirements

### Requirement: Hook runner emits tool_call telemetry on PostToolUse path
When the hook runner processes a `PostToolUse` hook invocation, it SHALL call `telemetry_collector.record_tool_call(...)` with the tool name, truncated args preview, measured duration, success flag, and error details (if failed). The emission SHALL read `current_turn_id` from the telemetry contextvar to populate `parent_turn_id`.

#### Scenario: Successful tool call emits tool_call event
- **WHEN** a tool runs successfully and the `PostToolUse` hook fires
- **THEN** one `tool_call` event SHALL be emitted with `tool_name`, `duration_ms`, `success=true`, and the current `turn_id` as `parent_turn_id`

#### Scenario: Failed tool call records error details
- **WHEN** a tool raises an exception and the `PostToolUse` hook fires with the failure
- **THEN** the `tool_call` event SHALL have `success=false`, `error_type` set to the exception class, and `error_msg` truncated to 500 chars
- **AND** a separate `error` event SHALL be emitted with `source='tool'`

#### Scenario: args_preview respects configured length
- **WHEN** `telemetry.preview_length=30` and a tool is called with a 200-char argument string
- **THEN** `tool_call.args_preview` SHALL be exactly 30 chars

### Requirement: Hook runner emits hook_event for each hook invocation
After each hook returns a decision, the hook runner SHALL emit a `hook_event` with the hook type, decision outcome, measured latency, and matched rule identifier (if any).

#### Scenario: PreToolUse hook allows a tool
- **WHEN** a `PreToolUse` hook runs and returns `allow`
- **THEN** one `hook_event` SHALL be emitted with `hook_type='PreToolUse'`, `decision='allow'`, and the measured `latency_ms`

#### Scenario: PreToolUse hook denies a tool
- **WHEN** a `PreToolUse` hook returns `deny`
- **THEN** the `hook_event` SHALL have `decision='deny'` and `rule_matched` populated if a specific rule triggered the denial
