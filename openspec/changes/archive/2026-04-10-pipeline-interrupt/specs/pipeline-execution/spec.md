## MODIFIED Requirements

### Requirement: execute_pipeline function signature
`execute_pipeline(pipeline_name: str, run_id: str, project_id: int, user_input: str, permission_mode: PermissionMode = PermissionMode.NORMAL)` SHALL load the pipeline YAML, execute all nodes via LangGraph StateGraph, and return results. The function SHALL NOT create a WorkflowRun — the caller provides a valid run_id. It SHALL fire PipelineStart hook at the beginning and PipelineEnd hook at the end. The `permission_mode` parameter SHALL default to `PermissionMode.NORMAL` (this is the only place in the codebase with a default value for permission_mode).

#### Scenario: Successful execution
- **WHEN** execute_pipeline is called with a valid pipeline_name and run_id
- **THEN** it SHALL build a LangGraph StateGraph via build_graph, invoke it with initial PipelineState, and return a PipelineResult with status='completed'

#### Scenario: Pipeline with interrupt returns paused
- **WHEN** execute_pipeline runs a pipeline where a node has interrupt: true
- **THEN** it SHALL return a PipelineResult with status='paused' and paused_at set to the interrupting node name

#### Scenario: PipelineStart hook fires at beginning
- **WHEN** execute_pipeline is called
- **THEN** a PipelineStart hook event SHALL fire before graph.invoke()

#### Scenario: PipelineEnd hook fires on completion
- **WHEN** pipeline execution finishes (success, failure, or pause)
- **THEN** a PipelineEnd hook event SHALL fire with the appropriate status

#### Scenario: Permission mode passed through state
- **WHEN** execute_pipeline is called with permission_mode=STRICT
- **THEN** PipelineState.permission_mode SHALL be "STRICT" and every node SHALL use it

### Requirement: Reactive scheduling — ready nodes start immediately
LangGraph StateGraph SHALL handle scheduling: nodes whose dependencies are satisfied SHALL be executed. For fan-out topologies, LangGraph's native parallel execution SHALL run independent nodes concurrently.

#### Scenario: Independent nodes run in parallel
- **WHEN** nodes A and B have no input (both are entry nodes)
- **THEN** LangGraph SHALL execute both concurrently

#### Scenario: Dependent node waits for upstream
- **WHEN** node C has input [findings] and node A produces findings
- **THEN** LangGraph SHALL NOT execute node C until node A completes

## ADDED Requirements

### Requirement: Internal scheduling replaced by LangGraph
The while-loop + asyncio.wait scheduling in execute_pipeline SHALL be replaced by LangGraph StateGraph.invoke(). The pending/running/completed set tracking SHALL be removed. LangGraph manages execution order based on the graph topology.

#### Scenario: No while-loop in execute_pipeline
- **WHEN** execute_pipeline is implemented
- **THEN** it SHALL NOT contain a while-loop for node scheduling; LangGraph handles this

#### Scenario: Graph invocation with checkpointer
- **WHEN** execute_pipeline calls graph.invoke()
- **THEN** it SHALL pass config with thread_id=run_id and use the shared PostgresSaver checkpointer
