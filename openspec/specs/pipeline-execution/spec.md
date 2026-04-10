## Purpose
Defines the execute_pipeline function that runs a pipeline end-to-end via LangGraph StateGraph, including hook lifecycle, checkpointing, and result reporting.
## Requirements
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

### Requirement: WorkflowRun status updates during execution
execute_pipeline SHALL update the WorkflowRun status: pending→running at start, running→completed or running→failed at end, using the existing `update_run_status` and `finish_run` functions.

#### Scenario: Status progression on success
- **WHEN** all nodes complete successfully
- **THEN** the WorkflowRun SHALL transition pending→running→completed with finished_at set

#### Scenario: Status progression on failure
- **WHEN** any node fails
- **THEN** the WorkflowRun SHALL transition pending→running→failed with finished_at set

### Requirement: Reactive scheduling — ready nodes start immediately
LangGraph StateGraph SHALL handle scheduling: nodes whose dependencies are satisfied SHALL be executed. For fan-out topologies, LangGraph's native parallel execution SHALL run independent nodes concurrently.

#### Scenario: Independent nodes run in parallel
- **WHEN** nodes A and B have no input (both are entry nodes)
- **THEN** LangGraph SHALL execute both concurrently

#### Scenario: Dependent node waits for upstream
- **WHEN** node C has input [findings] and node A produces findings
- **THEN** LangGraph SHALL NOT execute node C until node A completes

### Requirement: Node execution via create_agent and agent_loop
Each node SHALL be executed by calling `create_agent(role, task_description, project_id, run_id, abort_signal, permission_mode)` followed by `run_agent_to_completion(state)`. The exit reason SHALL be read from `state.exit_reason`. The final output SHALL be extracted using `extract_final_output(state.messages)`.

#### Scenario: Node uses role file
- **WHEN** a node has role='researcher'
- **THEN** create_agent SHALL be called with role='researcher', loading agents/researcher.md

### Requirement: Entry node task_description is user_input
For entry nodes (no input), the task_description passed to create_agent SHALL be the user_input string provided to execute_pipeline.

#### Scenario: Entry node receives user input
- **WHEN** an entry node executes with user_input="Write a blog about Rust async"
- **THEN** create_agent SHALL receive task_description="Write a blog about Rust async"

### Requirement: Non-entry node task_description includes upstream outputs
For non-entry nodes, the task_description SHALL include all upstream outputs, formatted as labeled sections. Each input SHALL appear as a section header with the input name followed by the content.

#### Scenario: Single upstream output
- **WHEN** node writer has input=[findings] and node_outputs contains findings="Research results..."
- **THEN** task_description SHALL contain the findings content in a labeled section

#### Scenario: Multiple upstream outputs
- **WHEN** node editor has input=[draft, feedback]
- **THEN** task_description SHALL contain both draft and feedback in separate labeled sections

### Requirement: Task record created for each node
Each node execution SHALL create a Task record via create_task with the run_id, and update it via complete_task (on success) or fail_task (on failure).

#### Scenario: Successful node creates and completes task
- **WHEN** a node completes successfully
- **THEN** a Task SHALL exist with status='completed' and result containing the node output

#### Scenario: Failed node creates and fails task
- **WHEN** a node fails with an exception
- **THEN** a Task SHALL exist with status='failed' and result containing the error

### Requirement: Failed node marks downstream as skipped
When a node fails, the engine SHALL identify all transitive downstream nodes (nodes that directly or indirectly depend on the failed node's output) and mark them as skipped. Nodes on unrelated branches SHALL continue executing.

#### Scenario: Downstream cascade
- **WHEN** node A fails, and node B depends on A's output, and node C depends on B's output
- **THEN** both B and C SHALL be marked as skipped

#### Scenario: Unrelated branch continues
- **WHEN** node A fails, but node D has no dependency on A
- **THEN** node D SHALL continue executing normally

### Requirement: PipelineResult contains all intermediate outputs
`PipelineResult` SHALL be a dataclass with fields: run_id (str), status (str: 'completed'/'failed'), outputs (dict[str, str]: all node outputs keyed by output name), final_output (str: the terminal node's output), failed_node (str | None), error (str | None).

#### Scenario: Successful pipeline result
- **WHEN** all nodes complete
- **THEN** PipelineResult.status SHALL be 'completed', outputs SHALL contain all node outputs, final_output SHALL be the terminal node's output

#### Scenario: Failed pipeline result
- **WHEN** node 'writer' fails with error "LLM timeout"
- **THEN** PipelineResult.status SHALL be 'failed', failed_node SHALL be 'writer', error SHALL contain "LLM timeout", outputs SHALL contain outputs from nodes that completed before the failure

### Requirement: Abort signal shared across all nodes
execute_pipeline SHALL create a single asyncio.Event as abort_signal and pass it to all node agents via create_agent. If the signal is set, running agents SHALL abort at their next check point.

#### Scenario: Abort propagation
- **WHEN** abort_signal is set during pipeline execution
- **THEN** all currently running node agents SHALL detect the abort and exit

### Requirement: Pipeline YAML resolution
Pipeline YAML files SHALL be resolved from a `pipelines/` directory relative to the project root. The pipeline_name parameter maps to `pipelines/{pipeline_name}.yaml`.

#### Scenario: Resolve pipeline path
- **WHEN** execute_pipeline is called with pipeline_name='blog_generation'
- **THEN** it SHALL load from `pipelines/blog_generation.yaml`

### Requirement: Internal scheduling replaced by LangGraph
The while-loop + asyncio.wait scheduling in execute_pipeline SHALL be replaced by LangGraph StateGraph.invoke(). The pending/running/completed set tracking SHALL be removed. LangGraph manages execution order based on the graph topology.

#### Scenario: No while-loop in execute_pipeline
- **WHEN** execute_pipeline is implemented
- **THEN** it SHALL NOT contain a while-loop for node scheduling; LangGraph handles this

#### Scenario: Graph invocation with checkpointer
- **WHEN** execute_pipeline calls graph.invoke()
- **THEN** it SHALL pass config with thread_id=run_id and use the shared PostgresSaver checkpointer

