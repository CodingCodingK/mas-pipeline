## Purpose
Defines how user requests are dispatched: `run_coordinator` runs the autonomous coordinator loop, while pipeline routing is the caller's responsibility.
## Requirements
### Requirement: coordinator-routing capability is deprecated
The `coordinator-routing` capability SHALL be retained as a deprecation marker only. Routing is now performed at the HTTP layer via the REST API; in-process `run_coordinator` no longer exists. New code SHALL NOT depend on this capability.

#### Scenario: HTTP layer owns routing
- **WHEN** a client wants to trigger a pipeline
- **THEN** it SHALL POST to `/api/projects/{id}/pipelines/{name}/runs`
- **AND** chat/autonomous sessions SHALL go through `/api/sessions/{id}/messages` instead

### Requirement: coordinator-routing capability remains deprecated
The `coordinator-routing` capability SHALL remain a deprecation marker; routing now happens at the HTTP layer via the REST API. Code SHALL NOT depend on this capability.

#### Scenario: HTTP routing
- **WHEN** a client triggers a pipeline
- **THEN** it SHALL POST to `/api/projects/{id}/pipelines/{name}/runs`
- **AND** chat/autonomous sessions SHALL use `/api/sessions/{id}/messages`

