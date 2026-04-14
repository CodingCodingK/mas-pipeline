## ADDED Requirements

### Requirement: SessionRunner dispatches clawbot factory by role
`SessionRunner._build_agent_state` SHALL contain exactly one role-aware branch: when the resolved role equals `"clawbot"`, it SHALL call `src/clawbot/factory.py::create_clawbot_agent(...)` instead of the generic `create_agent(...)`. For every other role the existing generic `create_agent(...)` path SHALL be used unchanged.

This is the only clawbot-aware code outside of `src/clawbot/`. The generic `src/agent/factory.py`, `src/agent/context.py`, and `src/agent/loop.py` SHALL remain untouched.

#### Scenario: clawbot role dispatches to clawbot factory
- **WHEN** a SessionRunner is built with mode `bus_chat` (resolving to role `clawbot`)
- **THEN** `_build_agent_state` SHALL call `create_clawbot_agent(...)` and the returned state's first system message SHALL contain the SOUL bootstrap content

#### Scenario: Other roles dispatch to generic factory
- **WHEN** a SessionRunner is built with mode `chat` or `autonomous`
- **THEN** `_build_agent_state` SHALL call the generic `create_agent(...)` and SHALL NOT touch any clawbot module

### Requirement: SessionRunner accepts bus_chat mode
The `_MODE_TO_ROLE` mapping in `src/engine/session_runner.py` SHALL include the entry `"bus_chat": "clawbot"`. Constructing a `SessionRunner(mode="bus_chat", ...)` SHALL build an agent state for the `clawbot` role.

#### Scenario: bus_chat mode resolves to clawbot role
- **WHEN** `SessionRunner(session_id=1, mode="bus_chat", project_id=1)` is constructed and started
- **THEN** the agent state SHALL be built via `create_clawbot_agent(...)` with role `clawbot`

#### Scenario: Existing modes unchanged
- **WHEN** a SessionRunner is constructed with `mode="chat"` or `mode="autonomous"`
- **THEN** the role resolution SHALL continue to map to `assistant` or `coordinator` respectively, and no clawbot module SHALL be imported
