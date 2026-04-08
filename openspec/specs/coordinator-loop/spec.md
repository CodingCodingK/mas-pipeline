## ADDED Requirements

### Requirement: coordinator_loop wraps agent_loop with outer do-while
`coordinator_loop(state: AgentState) -> ExitReason` SHALL wrap agent_loop in an outer loop that waits for sub-agent notifications after each agent_loop exit.

#### Scenario: No running agents after agent_loop
- **WHEN** agent_loop exits with COMPLETED
- **AND** state.running_agent_count is 0
- **THEN** coordinator_loop SHALL exit immediately with COMPLETED

#### Scenario: Running agents still active
- **WHEN** agent_loop exits with COMPLETED
- **AND** state.running_agent_count > 0
- **THEN** coordinator_loop SHALL await state.notification_queue.get()

### Requirement: Notification queue drives the wait loop
coordinator_loop SHALL use `await state.notification_queue.get()` to wait for sub-agent completion. No DB polling, no sleep loops.

#### Scenario: Await notification
- **WHEN** coordinator_loop is waiting for sub-agents
- **THEN** it SHALL block on `await state.notification_queue.get()` until a notification arrives
- **AND** zero LLM calls and zero DB queries SHALL occur during the wait

#### Scenario: Drain all available notifications
- **WHEN** a notification arrives and more notifications are immediately available
- **THEN** coordinator_loop SHALL drain all available notifications via get_nowait() before re-entering agent_loop

### Requirement: Notification injection as user message
When a notification arrives, coordinator_loop SHALL append it to state.messages as a user-role message before re-entering agent_loop.

#### Scenario: Completed agent notification
- **WHEN** agent_run #42 (role=researcher) completes with result="findings..."
- **THEN** a message SHALL be appended to state.messages with role="user" and content containing the `<task-notification>` XML

#### Scenario: Failed agent notification
- **WHEN** agent_run #43 (role=writer) fails with error="timeout"
- **THEN** a message SHALL be appended with role="user" containing the failure notification

### Requirement: coordinator_loop re-enters agent_loop after notification injection
After injecting notifications, coordinator_loop SHALL call agent_loop(state) again to let the LLM process the results.

#### Scenario: Re-entry cycle
- **WHEN** notifications have been injected
- **THEN** agent_loop SHALL be called again
- **AND** the cycle repeats (check running_agent_count after exit)

#### Scenario: All agents complete after re-entry
- **WHEN** agent_loop exits after processing notifications
- **AND** state.running_agent_count is 0
- **THEN** coordinator_loop SHALL exit with COMPLETED

### Requirement: Zero LLM cost during wait
The notification wait SHALL NOT make any LLM API calls. Only asyncio.Queue operations are allowed during the wait phase.

#### Scenario: Waiting for slow agent
- **WHEN** a background agent takes 30 seconds to complete
- **THEN** during those 30 seconds, zero LLM calls SHALL be made

### Requirement: notification_queue initialized by coordinator_loop
coordinator_loop SHALL set `state.notification_queue = asyncio.Queue()` and `state.running_agent_count = 0` before the first agent_loop call.

#### Scenario: Queue initialization
- **WHEN** coordinator_loop is called
- **THEN** state.notification_queue SHALL be an asyncio.Queue instance
- **AND** state.running_agent_count SHALL be 0
