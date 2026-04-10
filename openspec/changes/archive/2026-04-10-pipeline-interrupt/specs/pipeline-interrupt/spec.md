## ADDED Requirements

### Requirement: YAML interrupt configuration
A pipeline YAML node MAY include an `interrupt: true` field. When omitted or false, the node SHALL execute without pausing.

#### Scenario: Node with interrupt enabled
- **WHEN** a YAML node has `interrupt: true`
- **THEN** build_graph SHALL create two LangGraph nodes for it: an agent_run node and an interrupt_wait node

#### Scenario: Node without interrupt
- **WHEN** a YAML node has no `interrupt` field or `interrupt: false`
- **THEN** build_graph SHALL create a single LangGraph node for it

### Requirement: Interrupt node split to avoid agent re-execution
For nodes with `interrupt: true`, build_graph SHALL split them into two LangGraph nodes: `{name}_run` (executes agent) and `{name}_interrupt` (calls `interrupt()`). This ensures resume only re-executes the lightweight interrupt node, not the agent.

#### Scenario: Split node structure
- **WHEN** a node named "editor" has `interrupt: true`
- **THEN** build_graph SHALL create nodes "editor_run" → "editor_interrupt" with an edge between them

#### Scenario: Resume does not re-run agent
- **WHEN** a pipeline is resumed after pausing at "editor_interrupt"
- **THEN** only "editor_interrupt" SHALL re-execute (lightweight), "editor_run" SHALL NOT re-execute

#### Scenario: Interrupt payload contains node info
- **WHEN** `interrupt()` is called in the interrupt_wait node
- **THEN** the payload SHALL include the node name and the node's output content

### Requirement: resume_pipeline function
`resume_pipeline(run_id: str, feedback: str | None = None) -> PipelineResult` SHALL rebuild the graph, then call `graph.invoke(Command(resume=feedback), config={"configurable": {"thread_id": run_id}})` to resume from the checkpoint.

#### Scenario: Resume with feedback
- **WHEN** resume_pipeline is called with feedback="approved"
- **THEN** the graph SHALL continue from the interrupt point with the feedback value accessible

#### Scenario: Resume without feedback
- **WHEN** resume_pipeline is called with feedback=None
- **THEN** the graph SHALL continue from the interrupt point with None as resume value

#### Scenario: Resume non-existent run
- **WHEN** resume_pipeline is called with a run_id that has no checkpoint
- **THEN** it SHALL raise ValueError with a descriptive message

#### Scenario: Resume survives process restart
- **WHEN** the process restarts after a pipeline was paused (checkpoint in PG)
- **THEN** resume_pipeline SHALL successfully read the checkpoint from PG and continue execution

### Requirement: Pipeline status indicates paused state
`get_pipeline_status(run_id: str)` SHALL return the current status of a pipeline run, including whether it is paused and at which node.

#### Scenario: Running pipeline status
- **WHEN** get_pipeline_status is called for an active pipeline
- **THEN** it SHALL return status="running"

#### Scenario: Paused pipeline status
- **WHEN** get_pipeline_status is called for a pipeline paused at node "editor"
- **THEN** it SHALL return status="paused" with paused_at="editor"

#### Scenario: Completed pipeline status
- **WHEN** get_pipeline_status is called for a finished pipeline
- **THEN** it SHALL return status="completed"
