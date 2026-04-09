## MODIFIED Requirements

### Requirement: SpawnAgentTool launches a sub-agent asynchronously
`SpawnAgentTool.call(params, context)` SHALL create an AgentRun record (status=running), launch a sub-agent via `asyncio.create_task`, and immediately return the agent_run_id without blocking. The background coroutine SHALL use `run_agent_to_completion(state)` instead of `await agent_loop(state)`.

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

#### Scenario: Sub-agent exits with ERROR or ABORT
- **WHEN** a spawned sub-agent's run_agent_to_completion returns ExitReason.ERROR or ABORT
- **THEN** the background coroutine SHALL fail_agent_run and push notification
