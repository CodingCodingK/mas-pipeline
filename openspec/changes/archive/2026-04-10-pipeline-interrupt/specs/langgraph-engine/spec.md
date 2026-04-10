## ADDED Requirements

### Requirement: PipelineState TypedDict
`PipelineState` SHALL be a TypedDict with fields: `user_input` (str), `outputs` (Annotated[dict[str, str], merge_dicts] — merge reducer for parallel safety), `run_id` (str), `project_id` (int), `permission_mode` (str), `error` (str | None — set on node failure).

#### Scenario: State initialization
- **WHEN** a pipeline starts with user_input="Write a blog", run_id="run-1", project_id=1
- **THEN** PipelineState SHALL be initialized with those values, outputs={}, and error=None

#### Scenario: Parallel nodes merge outputs
- **WHEN** parallel nodes A and B complete, A returns outputs={"a": "..."} and B returns outputs={"b": "..."}
- **THEN** PipelineState.outputs SHALL contain both {"a": "...", "b": "..."} (merged, not overwritten)

### Requirement: build_graph constructs StateGraph from PipelineDefinition
`build_graph(pipeline_def: PipelineDefinition) -> CompiledGraph` SHALL dynamically construct a LangGraph StateGraph where each YAML node becomes a graph node, and edges are derived from input/output dependencies.

#### Scenario: Linear pipeline (A → B → C)
- **WHEN** PipelineDefinition has nodes A(output=a), B(input=[a], output=b), C(input=[b], output=c)
- **THEN** build_graph SHALL create a graph with edges START→A, A→B, B→C, C→END

#### Scenario: Fan-out pipeline (A → B, A → C, B+C → D)
- **WHEN** node A produces output "a", nodes B and C both take input [a], node D takes input [b, c]
- **THEN** build_graph SHALL create edges so B and C can run in parallel after A, and D waits for both

#### Scenario: Single-node pipeline
- **WHEN** PipelineDefinition has only one node
- **THEN** build_graph SHALL create a graph with edges START→node→END

### Requirement: Node function wraps existing _run_node logic
Each graph node function SHALL call `create_agent` + `run_agent_to_completion` + `extract_final_output` for its corresponding pipeline node, reading upstream outputs from `state["outputs"]` and writing its own output back.

#### Scenario: Entry node receives user_input as task_description
- **WHEN** a node has no input dependencies
- **THEN** the node function SHALL pass `state["user_input"]` as task_description to create_agent

#### Scenario: Non-entry node receives upstream outputs
- **WHEN** a node has input=[findings, analysis]
- **THEN** the node function SHALL format the upstream outputs from `state["outputs"]` as labeled sections in task_description

#### Scenario: Node writes output to state
- **WHEN** a node with output="draft" completes successfully
- **THEN** `state["outputs"]["draft"]` SHALL contain the extracted output

### Requirement: Node function creates Task records
Each node function SHALL create a Task record via `create_task` at the start and update it via `complete_task` (success) or `fail_task` (failure), consistent with existing pipeline behavior.

#### Scenario: Successful node updates task
- **WHEN** a node completes successfully
- **THEN** a Task record SHALL exist with status='completed'

#### Scenario: Failed node updates task
- **WHEN** a node raises an exception
- **THEN** a Task record SHALL exist with status='failed'

### Requirement: Node function captures non-serializable deps via closure
Node functions SHALL capture hook_runner, mcp_manager, abort_signal, and run_id_int via closure (not in PipelineState), because these objects cannot be JSON-serialized to checkpoint.

#### Scenario: Non-serializable objects not in state
- **WHEN** a node function executes
- **THEN** hook_runner, mcp_manager, abort_signal, run_id_int SHALL be accessed from closure, NOT from PipelineState

### Requirement: Node failure writes error to state
When a node's agent execution raises an exception, the node function SHALL catch it, write the error to `state["error"]`, and return normally (not re-raise). A conditional edge after each node SHALL check `state["error"]` and route to END if set.

#### Scenario: Node failure routes to END
- **WHEN** node A fails with an exception
- **THEN** state["error"] SHALL contain the error message, and the conditional edge SHALL route to END (skipping all downstream nodes)

#### Scenario: Unrelated branches not affected by error routing
- **WHEN** the graph has independent branches and one branch fails
- **THEN** nodes on unrelated branches that have already started SHALL continue (LangGraph parallel semantics)

### Requirement: build_graph generates conditional edges for routes
When a node has `routes`, build_graph SHALL add a conditional edge after that node. The routing function SHALL read `state["outputs"][output_name]` and check each condition string using `in` (substring match). Error check takes priority: if `state["error"]` is set, route to END regardless of routes.

#### Scenario: Condition matches
- **WHEN** node reviewer's output contains "通过" and a route has `condition: "通过", target: publish`
- **THEN** the conditional edge SHALL route to node "publish"

#### Scenario: No condition matches, default used
- **WHEN** node reviewer's output is "需要修改" and no condition matches, but default is "revise"
- **THEN** the conditional edge SHALL route to node "revise"

#### Scenario: Error overrides routes
- **WHEN** node reviewer fails (state["error"] is set) and has routes defined
- **THEN** the conditional edge SHALL route to END, ignoring routes

#### Scenario: Node without routes uses normal edge
- **WHEN** a node has no `routes` field
- **THEN** build_graph SHALL use a normal edge (or error-check conditional edge) to its downstream nodes

### Requirement: Compiled graph accepts checkpointer parameter
`build_graph` SHALL compile the StateGraph with an optional `checkpointer` parameter. When provided, all state transitions are persisted via the checkpointer.

#### Scenario: Graph with checkpointer
- **WHEN** build_graph is called and the graph is compiled with a PostgresSaver checkpointer
- **THEN** every node execution SHALL create a checkpoint

#### Scenario: Graph without checkpointer
- **WHEN** build_graph is called and compiled without a checkpointer
- **THEN** the graph SHALL execute normally without persistence (useful for testing)
