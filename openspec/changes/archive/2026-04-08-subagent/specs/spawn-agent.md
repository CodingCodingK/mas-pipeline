## ADDED Requirements

### Requirement: SpawnAgentTool launches a sub-agent asynchronously
`SpawnAgentTool.call(params, context)` SHALL create a Task record, launch a sub-agent via `asyncio.create_task`, and immediately return the task_id without blocking.

#### Scenario: Spawn a sub-agent
- **WHEN** spawn_agent is called with role="researcher" and task_description="调研 Redis"
- **THEN** it SHALL:
  1. Create a Task record with subject="researcher: 调研 Redis", status="pending", run_id from ToolContext
  2. claim_task with agent_id formatted as `{run_id}:researcher`
  3. Launch `asyncio.create_task` to run `create_agent` + `agent_loop` in background
  4. Return ToolResult with output containing the task_id

#### Scenario: Sub-agent completes successfully
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.COMPLETED
- **THEN** the background coroutine SHALL:
  1. Extract the final output text (last assistant message with content, searching backwards)
  2. Call complete_task(task_id, output_text)

#### Scenario: Sub-agent exits with MAX_TURNS
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.MAX_TURNS
- **THEN** the background coroutine SHALL:
  1. Extract the last assistant content (if any)
  2. Call complete_task(task_id, "[MAX_TURNS] {content}")

#### Scenario: Sub-agent exits with ERROR or ABORT
- **WHEN** a spawned sub-agent's agent_loop returns ExitReason.ERROR or ABORT
- **THEN** the background coroutine SHALL call fail_task(task_id, "[ERROR] agent failed" or "[ABORT] agent aborted")

#### Scenario: Sub-agent raises unhandled exception
- **WHEN** the background coroutine for a sub-agent raises an exception
- **THEN** it SHALL call fail_task(task_id, error message) and NOT propagate the exception

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

#### Scenario: Last assistant has only tool_calls
- **GIVEN** messages ends with {"role": "assistant", "tool_calls": [...]} with no content
- **AND** an earlier message has {"role": "assistant", "content": "Intermediate result"}
- **THEN** extract_final_output SHALL return "Intermediate result"

#### Scenario: No assistant messages with content
- **GIVEN** messages contains no assistant messages with content
- **THEN** extract_final_output SHALL return ""
