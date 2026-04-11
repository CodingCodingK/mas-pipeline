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
When a spawned sub-agent finishes (any exit reason), the background coroutine SHALL persist its result as a `<task-notification>` user-role message into the parent conversation's `Conversation.messages` JSONB column via `append_message()`, then signal the parent SessionRunner via `wakeup.set()` (in-process) AND issue `NOTIFY session_wakeup, '<session_id>'` (for cross-process forward compatibility). The legacy `parent_state.notification_queue.put()` path is removed.

#### Scenario: Sub-agent completes successfully
- **WHEN** a spawned sub-agent's `run_agent_to_completion` returns ExitReason.COMPLETED
- **THEN** the background coroutine SHALL:
  1. Extract the final output text (last assistant message with content, searching backwards)
  2. Call `complete_agent_run(agent_run_id, output_text)`
  3. Append a `<task-notification>` user-role message into the parent `Conversation.messages` via `append_message(parent_conversation_id, message)`
  4. Call `parent_runner.wakeup.set()` if the parent SessionRunner is in the local registry
  5. Issue `NOTIFY session_wakeup, '<parent_session_id>'` on a short-lived PG connection
  6. Decrement `parent_state.running_agent_count` if `parent_state` is in-memory

#### Scenario: Sub-agent exits with MAX_TURNS
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.MAX_TURNS
- **THEN** the background coroutine SHALL `complete_agent_run`, append the notification message, and signal wakeup as above

#### Scenario: Sub-agent exits with ERROR or ABORT
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.ERROR or ABORT
- **THEN** the background coroutine SHALL `fail_agent_run`, append a failure `<task-notification>`, and signal wakeup as above

#### Scenario: Sub-agent raises unhandled exception
- **WHEN** the background coroutine for a sub-agent raises an exception
- **THEN** it SHALL call `fail_agent_run`, append a failure notification message, signal wakeup, fire SubagentEnd hook, and NOT propagate the exception

#### Scenario: Parent runner not in local registry
- **WHEN** the parent SessionRunner has already exited (no longer in local registry) at the time a sub-agent completes
- **THEN** the notification message SHALL still be appended to PG
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
