## MODIFIED Requirements

### Requirement: Node execution via create_agent and agent_loop
Each node SHALL be executed by calling `create_agent(role, task_description, project_id, run_id, abort_signal, permission_mode)` followed by `run_agent_to_completion(state)`. The returned `AgentRunResult` SHALL be used as the single source of truth: `exit_reason` for the status branch, `final_output` as the node output, and the three statistics (`tool_use_count`, `cumulative_tokens`, `duration_ms`) + `messages` passed through to `complete_agent_run` / `fail_agent_run`. The node SHALL NOT reach into `state.*` fields after `run_agent_to_completion` returns.

#### Scenario: Node uses role file
- **WHEN** a node has role='researcher'
- **THEN** create_agent SHALL be called with role='researcher', loading agents/researcher.md

#### Scenario: Successful node persists full transcript and statistics
- **WHEN** a pipeline node's agent finishes with AgentRunResult(exit_reason=COMPLETED, messages=[...20 dicts...], final_output="draft", tool_use_count=3, cumulative_tokens=6800, duration_ms=22000)
- **THEN** `_run_node` SHALL call `complete_agent_run(agent_run.id, "draft", [...20 dicts...], 3, 6800, 22000)`
- **AND** the agent_runs row SHALL contain the full transcript in the messages column and the three statistics columns populated

#### Scenario: MAX_TURNS node still persists transcript
- **WHEN** a node's agent hits ExitReason.MAX_TURNS with partial transcript accumulated
- **THEN** `_run_node` SHALL call `complete_agent_run` with the partial `messages` list and accumulated statistics, with result prefixed `[MAX_TURNS]`

#### Scenario: Failed node persists partial transcript
- **WHEN** a node's agent hits ExitReason.ERROR or raises an exception
- **THEN** `_run_node` SHALL call `fail_agent_run` with the partial `messages` list and accumulated statistics so the transcript is available for post-mortem
