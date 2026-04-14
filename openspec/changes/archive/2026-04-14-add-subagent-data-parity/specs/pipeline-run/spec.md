## ADDED Requirements

### Requirement: Pipeline run detail page exposes per-node agent run drawer
The `RunDetailPage` SHALL expose a per-node UI affordance (clickable row, button, or DAG node click) that opens the shared `AgentRunDetailDrawer` component for the agent_run associated with that node. The drawer SHALL fetch `GET /api/agent-runs/{id}` and render the same information as the chat variant (statistics header, description, transcript, result). This is a **frontend-only** addition; pipeline execution semantics SHALL NOT change.

The agent_run id for a given node SHALL be looked up via the existing `GET /api/runs/{run_id}/agent-runs` list response (matching by `role` or `owner`). This lookup SHALL be performed lazily when the user opens the drawer for a node, not on page load.

#### Scenario: Click node in pipeline run detail
- **WHEN** a user clicks a node (row or graph node) in `RunDetailPage`
- **THEN** the page SHALL find the matching `agent_run_id` from the list of agent runs for that workflow run
- **AND** SHALL open `AgentRunDetailDrawer` with that id
- **AND** the drawer SHALL display the agent's full transcript and statistics

#### Scenario: Node with no agent run (e.g., interrupt node)
- **WHEN** a user clicks a node whose type does not correspond to an agent run (e.g., a pure interrupt node)
- **THEN** the drawer SHALL NOT open
- **AND** the node row SHALL NOT appear clickable (or SHALL display a disabled state)

#### Scenario: Drawer shared across chat and pipeline contexts
- **WHEN** `AgentRunDetailDrawer` is used in either the chat page or the pipeline run detail page
- **THEN** the same component SHALL be used with the same props contract (`agentRunId`, `onClose`)
- **AND** the REST endpoint and response schema SHALL be identical for both contexts

#### Scenario: Statistics visible without opening drawer
- **WHEN** the per-node list view is rendered
- **THEN** each row representing an agent run SHALL display inline badges showing `tool_use_count`, `total_tokens`, `duration_ms` from the list response (these three fields remain in the list endpoint even though `messages` is excluded)
