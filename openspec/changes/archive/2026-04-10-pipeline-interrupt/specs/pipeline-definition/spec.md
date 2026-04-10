## MODIFIED Requirements

### Requirement: Node definition has four fields
Each node in the `nodes` list SHALL have: `name` (required, string), `role` (required, string), `output` (required, string), `input` (optional, list of strings), `interrupt` (optional, bool, default false), `routes` (optional, list of route objects). No other fields are used by the engine.

#### Scenario: Minimal node (entry node)
- **WHEN** a node has `name: researcher`, `role: researcher`, `output: findings` and no `input`
- **THEN** it SHALL be treated as an entry node with no dependencies, interrupt=false, and routes=[]

#### Scenario: Node with interrupt enabled
- **WHEN** a node has `name: editor`, `role: editor`, `output: edited_draft`, `interrupt: true`
- **THEN** the NodeDefinition SHALL have interrupt=True

#### Scenario: Node without interrupt field
- **WHEN** a node has no `interrupt` field
- **THEN** the NodeDefinition SHALL have interrupt=False (default)

#### Scenario: Node with routes
- **WHEN** a node has `routes: [{condition: "通过", target: publish}, {default: revise}]`
- **THEN** the NodeDefinition SHALL have routes parsed as a list of RouteDefinition objects

## ADDED Requirements

### Requirement: Route definition format
A route object SHALL have either `condition` (string) + `target` (string), or `default` (string). A node's `routes` list MAY contain multiple condition routes and at most one default route.

#### Scenario: Condition route
- **WHEN** a route has `condition: "通过"` and `target: publish`
- **THEN** it SHALL match when the node's output content contains the string "通过"

#### Scenario: Default route
- **WHEN** a route has `default: revise`
- **THEN** it SHALL be used when no condition route matches

#### Scenario: No default route and no match
- **WHEN** no condition matches and no default route is defined
- **THEN** load_pipeline SHALL raise ValueError indicating a missing default route

### Requirement: Routes validation
`load_pipeline` SHALL validate that route targets reference valid node names, and that a node with `routes` does not also appear as an implicit dependency via other nodes' `input` fields pointing to the same output.

#### Scenario: Invalid route target
- **WHEN** a route has `target: nonexistent` and no node named "nonexistent" exists
- **THEN** load_pipeline SHALL raise ValueError

#### Scenario: At most one default per node
- **WHEN** a node has two routes with `default` keys
- **THEN** load_pipeline SHALL raise ValueError

### Requirement: Dependency inference with routes
When a node has `routes`, the dependency graph SHALL treat the routing node's output as available to ALL route target nodes. Each target node still declares `input` to receive the output. The route determines WHICH target actually executes, not which has access.

#### Scenario: Route targets depend on routing node
- **WHEN** node reviewer has `routes: [{condition: "通过", target: publish}, {default: revise}]`
- **THEN** both publish and revise SHALL depend on reviewer in the dependency graph, but only one SHALL execute at runtime
