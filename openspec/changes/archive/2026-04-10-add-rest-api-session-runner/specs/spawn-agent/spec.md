## MODIFIED Requirements

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

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Notification queue integration
**Reason**: Replaced by PG-backed notification persistence + SessionRunner wakeup signaling. The in-process `parent_state.notification_queue` is no longer the transport for sub-agent results — `Conversation.messages` is the durable channel and `SessionRunner.wakeup` is the wake signal.
**Migration**: Code paths that previously enqueued to `parent_state.notification_queue` SHALL append a `<task-notification>` user message to `Conversation.messages` and call `parent_runner.wakeup.set()`. The `AgentState.notification_queue` field is removed; any reference to it must be deleted. Tests that previously asserted on queue contents SHALL instead assert on the conversation's messages list.

### Requirement: Notification format follows CC task-notification pattern
**Reason**: This requirement is preserved verbatim under the new "Sub-agent completion writes notification to conversation" requirement above (XML format unchanged). Listing it as REMOVED here only retires the standalone requirement entry that was scoped to the now-removed notification queue.
**Migration**: No content change — `format_task_notification()` is still used to build the message body, just routed to `append_message()` instead of `queue.put()`.
