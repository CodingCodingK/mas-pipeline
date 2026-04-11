## ADDED Requirements

### Requirement: spawn_agent emits agent_spawn event and propagates spawn_id
When `spawn_agent` tool is invoked to create a sub-agent, the implementation SHALL:

1. Generate a fresh UUID `spawn_id`
2. Emit one `agent_spawn` event with `parent_role` (from the calling agent's role), `child_role` (from the tool argument), `task_preview` (truncated per `preview_length`), `parent_turn_id` (from `current_turn_id` contextvar), and the generated `spawn_id`
3. Set `current_spawn_id.set(spawn_id)` on the telemetry contextvar **before** spawning the child agent's task via `asyncio.create_task`
4. The child agent's first `agent_turn` event SHALL read `current_spawn_id` on turn entry (via its inherited task context) and record it in `spawned_by_spawn_id`; subsequent turns of the same child SHALL NOT set `spawned_by_spawn_id` (it applies only to the first turn)

`spawn_agent` SHALL NOT pass `spawn_id` through agent parameters; contextvar inheritance via `asyncio.create_task` handles the propagation.

#### Scenario: Single spawn links parent and child
- **WHEN** agent A in turn `T1` calls `spawn_agent(role='researcher', task='search for X')`
- **THEN** an `agent_spawn` event SHALL be emitted with `parent_turn_id='T1'`, `parent_role='A'`, `child_role='researcher'`, and a fresh `spawn_id='S1'`
- **AND** the researcher's first `agent_turn` event SHALL have `spawned_by_spawn_id='S1'`

#### Scenario: Parallel spawns produce distinct spawn_ids
- **WHEN** agent A in turn `T1` calls `spawn_agent` twice concurrently (two parallel tool calls)
- **THEN** two distinct `agent_spawn` events SHALL be emitted with different `spawn_id` values
- **AND** each spawned child's first `agent_turn` SHALL have the `spawned_by_spawn_id` matching its respective parent spawn

#### Scenario: Only the first turn of the child records the link
- **WHEN** a spawned child completes its first turn and runs a second turn (autonomous mode continuation)
- **THEN** only the first turn's `agent_turn` event SHALL have `spawned_by_spawn_id` set
- **AND** subsequent turns SHALL have `spawned_by_spawn_id=null`
