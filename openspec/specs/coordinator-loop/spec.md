## Purpose
Defines `coordinator_loop`, the legacy outer wait loop around `agent_loop`.
## Requirements
### Requirement: coordinator-loop capability is deprecated
The `coordinator-loop` capability SHALL be retained as a deprecation marker only. All behavior previously owned by this capability is moved to `session-runner` (wait loop, wakeup) and `spawn-agent` (notification persistence). New code SHALL NOT depend on this capability.

#### Scenario: No code imports coordinator_loop
- **WHEN** any module is loaded in the project
- **THEN** it SHALL NOT import `src.engine.coordinator` (the file is removed)
- **AND** it SHALL NOT reference a `notification_queue` attribute on `AgentState`

### Requirement: coordinator-loop capability remains deprecated
The `coordinator-loop` capability SHALL remain a deprecation marker; the wait loop and notification gating responsibilities are owned by `session-runner` and `spawn-agent`. Code SHALL NOT depend on this capability.

#### Scenario: No imports
- **WHEN** any module is loaded
- **THEN** it SHALL NOT import `src.engine.coordinator`
- **AND** it SHALL NOT reference `notification_queue` on `AgentState`

