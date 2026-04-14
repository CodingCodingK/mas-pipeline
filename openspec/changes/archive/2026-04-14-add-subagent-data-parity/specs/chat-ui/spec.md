## ADDED Requirements

### Requirement: Task notification card opens agent run detail drawer
When the chat UI renders a message whose `metadata.kind === "task_notification"`, the rendered card SHALL be clickable. Clicking the card SHALL open a shared `AgentRunDetailDrawer` component with `agentRunId` derived from `metadata.agent_run_id`. The drawer SHALL fetch `GET /api/agent-runs/{id}` and render:
- A header row with role, status, and three statistics badges (tool_use_count / total_tokens / duration_ms)
- The original task description
- The full message transcript (rendered read-only via the existing assistant-ui message renderer)
- The final result text

The main agent LLM context SHALL NOT be affected by drawer interactions; the drawer is pure frontend display.

#### Scenario: Click task_notification card
- **WHEN** a user clicks a task_notification card in the chat message list
- **THEN** `AgentRunDetailDrawer` SHALL open with the correct `agentRunId`
- **AND** the drawer SHALL issue a `GET /api/agent-runs/{id}` request
- **AND** upon response SHALL display the role/status/statistics/description/transcript/result

#### Scenario: Card shows statistics badges inline
- **WHEN** a task_notification card is rendered from a message whose `metadata` includes `tool_use_count`, `total_tokens`, `duration_ms`
- **THEN** the card SHALL render three small badges showing "N tools · K tokens · Xs" next to the role + status line
- **AND** the badges SHALL be rendered directly from metadata without re-parsing the XML body

#### Scenario: Drawer closes cleanly
- **WHEN** the user clicks outside the drawer, presses Escape, or clicks the close button
- **THEN** the drawer SHALL close and in-flight requests SHALL be aborted
