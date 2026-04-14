## Purpose
Defines `SpawnAgentTool`: lets a parent agent launch sub-agents asynchronously and receive their results via the notification flow.
## Requirements
### Requirement: SpawnAgentTool launches a sub-agent asynchronously
`SpawnAgentTool.call(params, context)` SHALL create an AgentRun record (status=running), launch a sub-agent via `asyncio.create_task`, and immediately return the agent_run_id without blocking. It SHALL fire a SubagentStart hook event before launching and a SubagentEnd hook event when the background coroutine completes. The launched task SHALL be registered in `parent_runner.child_tasks` (if a parent SessionRunner exists in the local registry) so that runner shutdown cancels it.

#### Scenario: Spawn a sub-agent
- **WHEN** spawn_agent is called with role="researcher" and task_description="调研 Redis"
- **THEN** it SHALL:
  1. Create an AgentRun record with role="researcher", status="running", owner="{run_id}:researcher"
  2. Launch `asyncio.create_task` to run `create_agent` + `run_agent_to_completion` in background
  3. Register the task in `parent_runner.child_tasks` if available
  4. Return ToolResult with output containing the agent_run_id

#### Scenario: SubagentStart hook fires on spawn
- **WHEN** spawn_agent is called with role="researcher"
- **THEN** a SubagentStart hook event SHALL fire with payload containing agent_run_id, role, task_description, parent_run_id

#### Scenario: SubagentEnd hook fires on completion
- **WHEN** a spawned sub-agent finishes (any exit reason)
- **THEN** a SubagentEnd hook event SHALL fire with payload containing agent_run_id, role, status, result, parent_run_id

### Requirement: SpawnAgentTool input schema
The tool SHALL accept the following parameters:
- `role` (string, required): role file name (without .md extension)
- `task_description` (string, required): task for the sub-agent (injected as user message)
- `tools` (array of strings, optional): override role file tool whitelist

#### Scenario: Schema accepts role + task_description
- **WHEN** spawn_agent is invoked with `{role: "researcher", task_description: "..."}`
- **THEN** the call SHALL succeed and the optional `tools` field SHALL default to the role file's whitelist

### Requirement: extract_final_output retrieves last assistant text
`extract_final_output(messages)` SHALL search messages in reverse order for the last message with role=assistant and non-empty content string. If no such message exists, return empty string.

#### Scenario: Last message has content
- **GIVEN** messages ends with {"role": "assistant", "content": "Final answer"}
- **THEN** extract_final_output SHALL return "Final answer"

#### Scenario: No assistant messages with content
- **GIVEN** messages contains no assistant messages with content
- **THEN** extract_final_output SHALL return ""

### Requirement: Sub-agent completion writes notification to conversation
When a spawned sub-agent finishes (any exit reason), the background coroutine SHALL:

1. Call `run_agent_to_completion(state)` and receive an `AgentRunResult` containing `exit_reason`, `messages`, `final_output`, `tool_use_count`, `cumulative_tokens`, `duration_ms`
2. Call `complete_agent_run(agent_run_id, result, messages, tool_use_count, total_tokens, duration_ms)` (success path) or `fail_agent_run(...)` (failure path), passing the full fields from the `AgentRunResult`
3. Build a `<task-notification>` user-role message containing the six fields `agent-run-id`, `role`, `status`, `tool-use-count`, `total-tokens`, `duration-ms`, `result` (see separate requirement below for XML format)
4. Append the notification message into the parent `Conversation.messages` via `append_message(parent_conversation_id, message)`
5. Call `parent_runner.wakeup.set()` if the parent SessionRunner is in the local registry
6. Issue `NOTIFY session_wakeup, '<parent_session_id>'` on a short-lived PG connection
7. Decrement `parent_state.running_agent_count` if `parent_state` is in-memory

The main agent's LLM context SHALL receive the `<task-notification>` message via the normal conversation flow. The main agent SHALL NOT have any mechanism to read `agent_runs.messages` — strong isolation is enforced at the absence-of-tool level.

#### Scenario: Sub-agent completes successfully with statistics
- **WHEN** a spawned sub-agent's `run_agent_to_completion` returns AgentRunResult(exit_reason=COMPLETED, messages=[...30 dicts...], final_output="分析结果是...", tool_use_count=5, cumulative_tokens=12453, duration_ms=47123)
- **THEN** the background coroutine SHALL:
  1. Call `complete_agent_run(agent_run_id, "分析结果是...", [...30 dicts...], 5, 12453, 47123)`
  2. Append a `<task-notification>` user-role message with the six fields populated
  3. Signal wakeup as defined

#### Scenario: Sub-agent exits with MAX_TURNS
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.MAX_TURNS
- **THEN** the background coroutine SHALL `complete_agent_run` with the partial transcript + accumulated statistics, append the notification message with `<status>max_turns</status>`, and signal wakeup as above

#### Scenario: Sub-agent exits with ERROR or ABORT
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.ERROR or ABORT
- **THEN** the background coroutine SHALL `fail_agent_run` with the partial transcript + statistics, append a failure `<task-notification>` with the same six fields (statistics reflect whatever accumulated before failure, may be 0), and signal wakeup as above

#### Scenario: Sub-agent raises unhandled exception
- **WHEN** the background coroutine for a sub-agent raises an exception
- **THEN** it SHALL call `fail_agent_run` with whatever `state.messages` / counters were accumulated, append a failure notification message with statistics fields, signal wakeup, fire SubagentEnd hook, and NOT propagate the exception

#### Scenario: Parent runner not in local registry
- **WHEN** the parent SessionRunner has already exited (no longer in local registry) at the time a sub-agent completes
- **THEN** the notification message (including statistics fields) SHALL still be appended to PG
- **AND** only the `NOTIFY session_wakeup` signal SHALL be issued (in-process wakeup is skipped)
- **AND** when the user later POSTs a new message, a fresh SessionRunner SHALL be created and load the notification from history

### Requirement: spawn_agent emits agent_spawn event and propagates spawn_id
When `spawn_agent` tool is invoked to create a sub-agent, the implementation SHALL:

1. Generate a fresh UUID `spawn_id`
2. Emit one `agent_spawn` event with `parent_role` (from the calling agent's role), `child_role` (from the tool argument), `task_preview` (truncated per `preview_length`), `parent_turn_id` (from `current_turn_id` contextvar), and the generated `spawn_id`
3. Set `current_spawn_id.set(spawn_id)` on the telemetry contextvar **before** spawning the child agent's task via `asyncio.create_task`
4. The child agent's first `agent_turn` event SHALL read `current_spawn_id` on turn entry (via its inherited task context) and record it in `spawned_by_spawn_id`; subsequent turns of the same child SHALL NOT set `spawned_by_spawn_id` (it applies only to the first turn)

`spawn_agent` SHALL NOT pass `spawn_id` through agent parameters; contextvar inheritance via `asyncio.create_task` handles the propagation.

#### Scenario: Single spawn links parent and child
- **WHEN** agent A in turn `T1` calls `spawn_agent(role='researcher', task='search for X')`
- **THEN** an `agent_spawn` event SHALL be emitted with `parent_turn_id='T1'`, `parent_role='A'`, `child_role='researcher'`, and a fresh `spawn_id='S1'`
- **AND** the researcher's first `agent_turn` event SHALL have `spawned_by_spawn_id='S1'`

#### Scenario: Parallel spawns produce distinct spawn_ids
- **WHEN** agent A in turn `T1` calls `spawn_agent` twice concurrently (two parallel tool calls)
- **THEN** two distinct `agent_spawn` events SHALL be emitted with different `spawn_id` values
- **AND** each spawned child's first `agent_turn` SHALL have the `spawned_by_spawn_id` matching its respective parent spawn

#### Scenario: Only the first turn of the child records the link
- **WHEN** a spawned child completes its first turn and runs a second turn (autonomous mode continuation)
- **THEN** only the first turn's `agent_turn` event SHALL have `spawned_by_spawn_id` set
- **AND** subsequent turns SHALL have `spawned_by_spawn_id=null`

### Requirement: task-notification XML includes three statistics fields
The `format_task_notification` helper SHALL produce an XML string with the following field order, including three statistics fields inserted between `<status>` and `<result>`:

```xml
<task-notification>
<agent-run-id>{agent_run_id}</agent-run-id>
<role>{role}</role>
<status>{status}</status>
<tool-use-count>{tool_use_count}</tool-use-count>
<total-tokens>{total_tokens}</total-tokens>
<duration-ms>{duration_ms}</duration-ms>
<result>{result}</result>
</task-notification>
```

Field names SHALL use kebab-case. Statistics values SHALL be integers rendered as decimal strings. All six fields SHALL always be present (even for failed or max_turns outcomes).

#### Scenario: Format includes all statistics
- **WHEN** `format_task_notification(agent_run_id=42, role="analyst", status="completed", tool_use_count=5, total_tokens=12453, duration_ms=47123, result="hello")` is called
- **THEN** the returned string SHALL contain `<tool-use-count>5</tool-use-count>`, `<total-tokens>12453</total-tokens>`, `<duration-ms>47123</duration-ms>` in that order between `<status>` and `<result>`

#### Scenario: Failed sub-agent notification
- **WHEN** a failed sub-agent has 0 tool calls, 0 tokens (nothing was accumulated before crash)
- **THEN** the notification XML SHALL contain `<tool-use-count>0</tool-use-count>`, `<total-tokens>0</total-tokens>`, `<duration-ms>{small}</duration-ms>` with status=failed

#### Scenario: task_notification message metadata includes statistics
- **WHEN** `_build_notification_message` constructs the dict
- **THEN** the `metadata` dict SHALL include `tool_use_count`, `total_tokens`, `duration_ms` keys alongside the existing `kind` / `agent_run_id` / `sub_agent_role` / `status` keys so the frontend can render badges without re-parsing XML

### Requirement: Sub-agent disallowed roles blacklist
`src/tools/builtins/spawn_agent.py` SHALL define a module-level constant `SUB_AGENT_DISALLOWED_ROLES: frozenset[str] = frozenset({"clawbot"})`. On every `SpawnAgentTool.call(params, context)` invocation, the tool SHALL check `params["role"]` against this set as the first action in `call`, and if matched return `ToolResult(success=False, output="role '<role>' cannot be spawned as a sub-agent")` without creating an `AgentRun` row, without firing hook events, and without launching any task.

The check exists to prevent `clawbot` (the top-level group-chat router) from being recursively spawned by other agents — it owns its own progress-reporting and pending-run lifecycle that does not make sense inside a sub-agent context.

#### Scenario: Spawning clawbot is rejected
- **WHEN** any agent calls `spawn_agent` with `role="clawbot"`
- **THEN** the tool SHALL return `ToolResult(success=False)` with a message indicating the role is not spawnable
- **AND** no `AgentRun` row SHALL be created
- **AND** no `SubagentStart` hook SHALL fire
- **AND** no `asyncio.create_task` SHALL be launched

#### Scenario: Other roles still spawn normally
- **WHEN** any agent calls `spawn_agent` with `role="researcher"`
- **THEN** the existing spawn path SHALL execute unchanged (AgentRun created, hook fires, task launched)

#### Scenario: Blacklist is a single source of truth
- **WHEN** future roles need to be added to the blacklist
- **THEN** they SHALL be added to `SUB_AGENT_DISALLOWED_ROLES` and no other code path SHALL need updating

