## MODIFIED Requirements

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

## ADDED Requirements

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
