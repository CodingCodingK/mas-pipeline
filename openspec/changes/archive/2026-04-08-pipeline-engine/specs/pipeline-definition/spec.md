## ADDED Requirements

### Requirement: YAML pipeline definition format
A pipeline YAML file SHALL contain a top-level `pipeline` (string name), `description` (string), and `nodes` (list). No `edges` section.

#### Scenario: Valid pipeline file
- **WHEN** a YAML file contains `pipeline: blog_generation`, `description: ...`, and a `nodes` list
- **THEN** it SHALL be accepted as a valid pipeline definition

#### Scenario: Missing pipeline name
- **WHEN** a YAML file has no `pipeline` field
- **THEN** load_pipeline SHALL raise ValueError

### Requirement: Node definition has four fields
Each node in the `nodes` list SHALL have: `name` (required, string), `role` (required, string), `output` (required, string), `input` (optional, list of strings). No other fields are used by the engine.

#### Scenario: Minimal node (entry node)
- **WHEN** a node has `name: researcher`, `role: researcher`, `output: findings` and no `input`
- **THEN** it SHALL be treated as an entry node with no dependencies

#### Scenario: Node with dependencies
- **WHEN** a node has `input: [findings, analysis]`
- **THEN** the node depends on whichever nodes produce the outputs named `findings` and `analysis`

### Requirement: Dependency inference from input/output
`load_pipeline` SHALL build a dependency graph by scanning all nodes' `output` fields to create an `output_name → node_name` mapping, then translating each node's `input` list into a set of dependency node names.

#### Scenario: Automatic dependency resolution
- **WHEN** node A declares `output: findings` and node B declares `input: [findings]`
- **THEN** node B SHALL depend on node A

#### Scenario: Multiple dependencies
- **WHEN** node C declares `input: [findings, analysis]`, node A declares `output: findings`, node B declares `output: analysis`
- **THEN** node C SHALL depend on both node A and node B

### Requirement: Output name uniqueness validation
`load_pipeline` SHALL raise ValueError if two nodes declare the same `output` name.

#### Scenario: Duplicate output
- **WHEN** node A and node B both declare `output: findings`
- **THEN** load_pipeline SHALL raise ValueError with a message identifying both nodes

### Requirement: Input reference validation
`load_pipeline` SHALL raise ValueError if any node's `input` references an output name that no node produces.

#### Scenario: Invalid input reference
- **WHEN** node B declares `input: [nonexistent]` and no node has `output: nonexistent`
- **THEN** load_pipeline SHALL raise ValueError identifying the bad reference and the node

### Requirement: Cycle detection
`load_pipeline` SHALL detect cycles in the dependency graph and raise ValueError if found.

#### Scenario: Direct cycle
- **WHEN** node A depends on node B and node B depends on node A
- **THEN** load_pipeline SHALL raise ValueError indicating a cycle

#### Scenario: Indirect cycle
- **WHEN** A → B → C → A forms a cycle
- **THEN** load_pipeline SHALL raise ValueError indicating a cycle

### Requirement: load_pipeline returns PipelineDefinition
`load_pipeline(yaml_path: str) -> PipelineDefinition` SHALL return a dataclass containing the pipeline name, description, list of node definitions, the `output_to_node` mapping, and the `dependencies` mapping (node_name → set of dependency node names).

#### Scenario: Successful load
- **WHEN** load_pipeline is called with a valid YAML path
- **THEN** it SHALL return a PipelineDefinition with all fields populated

### Requirement: Entry nodes identified
Entry nodes are nodes with no `input` (or empty `input` list). The PipelineDefinition SHALL expose which nodes are entry nodes via the dependencies mapping (empty dependency set).

#### Scenario: Identify entry nodes
- **WHEN** a pipeline has nodes researcher (no input) and writer (input: [findings])
- **THEN** researcher SHALL have an empty dependency set, writer SHALL not
