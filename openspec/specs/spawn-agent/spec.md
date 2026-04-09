## ADDED Requirements

### Requirement: SpawnAgentTool launches a sub-agent asynchronously
`SpawnAgentTool.call(params, context)` SHALL create an AgentRun record (status=running), launch a sub-agent via `asyncio.create_task`, and immediately return the agent_run_id without blocking.

#### Scenario: Spawn a sub-agent
- **WHEN** spawn_agent is called with role="researcher" and task_description="调研 Redis"
- **THEN** it SHALL:
  1. Create an AgentRun record with role="researcher", status="running", owner="{run_id}:researcher"
  2. Launch `asyncio.create_task` to run `create_agent` + `run_agent_to_completion` in background
  3. Return ToolResult with output containing the agent_run_id

#### Scenario: Sub-agent completes successfully
- **WHEN** a spawned sub-agent's run_agent_to_completion returns ExitReason.COMPLETED
- **THEN** the background coroutine SHALL:
  1. Extract the final output text (last assistant message with content, searching backwards)
  2. Call complete_agent_run(agent_run_id, output_text)
  3. Push a notification to parent_state.notification_queue

#### Scenario: Sub-agent exits with MAX_TURNS
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.MAX_TURNS
- **THEN** the background coroutine SHALL complete_agent_run and push notification

#### Scenario: Sub-agent exits with ERROR or ABORT
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.ERROR or ABORT
- **THEN** the background coroutine SHALL fail_agent_run and push notification

#### Scenario: Sub-agent raises unhandled exception
- **WHEN** the background coroutine for a sub-agent raises an exception
- **THEN** it SHALL call fail_agent_run, push notification, and NOT propagate the exception

### Requirement: Notification queue integration
When parent_state has a notification_queue (coordinator mode), spawn_agent SHALL push a notification dict on completion and maintain running_agent_count.

#### Scenario: Coordinator mode notification
- **WHEN** spawn_agent is called with parent_state.notification_queue set
- **THEN** running_agent_count SHALL increment on spawn and decrement on completion
- **AND** a notification dict SHALL be put into the queue with agent_run_id, role, status, result, and formatted message

#### Scenario: Non-coordinator mode (no queue)
- **WHEN** spawn_agent is called with parent_state.notification_queue as None
- **THEN** no notification SHALL be pushed and running_agent_count SHALL not change

### Requirement: Notification format follows CC task-notification pattern
Notifications SHALL use XML-style format via format_task_notification().

#### Scenario: Notification message content
- **WHEN** agent_run #42 (role=researcher) completes with result="findings..."
- **THEN** the notification message SHALL contain `<task-notification>`, agent-run-id, role, status, and result

### Requirement: SpawnAgentTool input schema
The tool SHALL accept the following parameters:
- `role` (string, required): role file name (without .md extension)
- `task_description` (string, required): task for the sub-agent (injected as user message)
- `tools` (array of strings, optional): override role file tool whitelist

### Requirement: extract_final_output retrieves last assistant text
`extract_final_output(messages)` SHALL search messages in reverse order for the last message with role=assistant and non-empty content string. If no such message exists, return empty string.

#### Scenario: Last message has content
- **GIVEN** messages ends with {"role": "assistant", "content": "Final answer"}
- **THEN** extract_final_output SHALL return "Final answer"

#### Scenario: No assistant messages with content
- **GIVEN** messages contains no assistant messages with content
- **THEN** extract_final_output SHALL return ""
