## ADDED Requirements

### Requirement: HookEventType enum covers all hook events
HookEventType SHALL be a str-based Enum with 9 values: PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE, SESSION_START, SESSION_END, SUBAGENT_START, SUBAGENT_END, PIPELINE_START, PIPELINE_END.

#### Scenario: HookEventType values are strings
- **WHEN** HookEventType.PRE_TOOL_USE is compared to the string "pre_tool_use"
- **THEN** the comparison SHALL be true (str Enum)

#### Scenario: All 9 events defined
- **WHEN** all HookEventType members are listed
- **THEN** there SHALL be exactly 9 members

### Requirement: HookEvent dataclass carries event payload
HookEvent SHALL be a dataclass with fields: `event_type` (HookEventType), `payload` (dict), `timestamp` (float, default=time.time()). The payload structure depends on the event type.

#### Scenario: PreToolUse payload
- **WHEN** a PreToolUse event is created
- **THEN** payload SHALL contain `tool_name` (str), `tool_input` (dict), `agent_id` (str), `run_id` (str)

#### Scenario: PostToolUse payload
- **WHEN** a PostToolUse event is created
- **THEN** payload SHALL contain `tool_name` (str), `tool_input` (dict), `tool_output` (str), `success` (bool), `agent_id` (str), `run_id` (str)

#### Scenario: PostToolUseFailure payload
- **WHEN** a PostToolUseFailure event is created
- **THEN** payload SHALL contain `tool_name` (str), `tool_input` (dict), `error` (str), `agent_id` (str), `run_id` (str)

#### Scenario: SubagentStart payload
- **WHEN** a SubagentStart event is created
- **THEN** payload SHALL contain `agent_run_id` (int), `role` (str), `task_description` (str), `parent_run_id` (str)

#### Scenario: SubagentEnd payload
- **WHEN** a SubagentEnd event is created
- **THEN** payload SHALL contain `agent_run_id` (int), `role` (str), `status` (str), `result` (str), `parent_run_id` (str)

#### Scenario: PipelineStart payload
- **WHEN** a PipelineStart event is created
- **THEN** payload SHALL contain `pipeline_name` (str), `run_id` (str), `project_id` (int), `user_input` (str)

#### Scenario: PipelineEnd payload
- **WHEN** a PipelineEnd event is created
- **THEN** payload SHALL contain `pipeline_name` (str), `run_id` (str), `status` (str), `error` (str | None)

#### Scenario: SessionStart payload
- **WHEN** a SessionStart event is created
- **THEN** payload SHALL contain `session_id` (str), `project_id` (int | None)

#### Scenario: SessionEnd payload
- **WHEN** a SessionEnd event is created
- **THEN** payload SHALL contain `session_id` (str), `reason` (str)

### Requirement: HookResult dataclass represents hook execution outcome
HookResult SHALL be a dataclass with fields: `action` (str: "allow"/"deny"/"modify", default="allow"), `reason` (str, default=""), `updated_input` (dict | None, default=None), `additional_context` (str, default="").

#### Scenario: Allow result
- **WHEN** a hook returns action="allow"
- **THEN** tool execution SHALL proceed normally

#### Scenario: Deny result
- **WHEN** a hook returns action="deny" with reason="Permission denied: shell not allowed for researcher"
- **THEN** tool execution SHALL be blocked and reason SHALL be returned to LLM as ToolResult error

#### Scenario: Modify result
- **WHEN** a hook returns action="modify" with updated_input={"command": "ls -la"}
- **THEN** tool execution SHALL proceed with the updated parameters

#### Scenario: Default result
- **WHEN** HookResult is constructed with no arguments
- **THEN** action SHALL be "allow", reason SHALL be "", updated_input SHALL be None, additional_context SHALL be ""

### Requirement: Aggregate multiple hook results
When multiple hooks fire for the same event, their results SHALL be aggregated: any "deny" wins over all "allow"/"modify"; if no deny, any "modify" applies (last modify wins); additional_context from all hooks SHALL be concatenated.

#### Scenario: One deny among allows
- **WHEN** three hooks return [allow, deny, allow]
- **THEN** aggregated result SHALL be deny

#### Scenario: Multiple modifies
- **WHEN** two hooks return modify with different updated_input
- **THEN** the last modify's updated_input SHALL be used

#### Scenario: Additional context from multiple hooks
- **WHEN** hook A returns additional_context="note A" and hook B returns additional_context="note B"
- **THEN** aggregated additional_context SHALL contain both "note A" and "note B"
