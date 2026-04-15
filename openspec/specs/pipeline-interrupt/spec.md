# pipeline-interrupt Specification

## Purpose
TBD - created by archiving change pipeline-interrupt. Update Purpose after archive.
## Requirements
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

The `interrupt()` call SHALL pass a payload of the shape `{node: string, output: string}` where `node` is the YAML node name and `output` is the string value of the node's configured `output_field` read verbatim from the `AgentState`. The payload SHALL NOT wrap, transform, or validate the output string — it is forwarded exactly as written.

The output string is markdown-shaped by convention across the shipped pipelines (`blog_with_review`, `courseware_exam`, `blog_generation`) but the pipeline engine SHALL NOT enforce markdown. Consumers of the interrupt payload (front-end renderers, review tooling) MUST treat `output` as an opaque string and MUST tolerate non-markdown content without crashing. Back-end code MUST NOT depend on markdown structure (no header parsing, no table extraction, no frontmatter assumptions).

#### Scenario: Split node structure
- **WHEN** a node named "editor" has `interrupt: true`
- **THEN** build_graph SHALL create nodes "editor_run" → "editor_interrupt" with an edge between them

#### Scenario: Resume does not re-run agent
- **WHEN** a pipeline is resumed after pausing at "editor_interrupt"
- **THEN** only "editor_interrupt" SHALL re-execute (lightweight), "editor_run" SHALL NOT re-execute

#### Scenario: Interrupt payload contains node info
- **WHEN** `interrupt()` is called in the interrupt_wait node
- **THEN** the payload SHALL include the node name and the node's output content

#### Scenario: Interrupt payload forwards output verbatim
- **GIVEN** a node whose `output_field` contains a plain-text string (no markdown headers, no code fences)
- **WHEN** the interrupt fires
- **THEN** the payload's `output` field SHALL be exactly the plain-text string with no wrapping or escaping applied by the engine

#### Scenario: Interrupt payload shape is consistent across pipelines
- **WHEN** `blog_with_review`, `courseware_exam`, and `blog_generation` each pause at their respective interrupt nodes
- **THEN** each interrupt payload SHALL have the same two top-level keys `node` and `output`
- **AND** `node` SHALL be a string equal to the paused node name
- **AND** `output` SHALL be a string

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

### Requirement: resume_pipeline three-way action contract

`resume_pipeline` SHALL support three distinct resume actions that shape what reaches the downstream graph:

- **approve**: The graph SHALL continue past the interrupt with `review_feedback=""` in the state. No user-provided text SHALL be injected into any downstream node's prompt. The approve action SHALL NOT carry an annotation field; any feedback passed alongside an approve action SHALL be discarded by the resume handler.
- **reject**: The graph SHALL reset the interrupted node's output to an empty string in the state, SHALL write the user-provided feedback into `review_feedback`, and SHALL re-execute the `{node}_run` node. The re-executed node MAY read `review_feedback` from its input state to incorporate the feedback into its next attempt.
- **edit**: The graph SHALL replace the interrupted node's output with the user-provided `edited` string in the state, SHALL set `review_feedback=""`, and SHALL proceed past the interrupt as if the node had originally produced the edited output.

The three actions are mutually exclusive: each resume call SHALL specify exactly one action, and the handler SHALL dispatch based on that action string.

#### Scenario: Approve drops any accompanying feedback

- **GIVEN** a pipeline paused at an interrupt
- **WHEN** `resume_pipeline` is invoked with `action="approve"` and a `feedback="looks good but consider X next time"` field
- **THEN** the graph state SHALL have `review_feedback=""` when downstream nodes read it
- **AND** no downstream node SHALL see the "looks good but consider X next time" text in its prompt

#### Scenario: Reject clears output and re-runs node with feedback

- **GIVEN** a pipeline paused at `editor_interrupt` with the `editor` node's output field set to the current draft
- **WHEN** `resume_pipeline` is invoked with `action="reject"` and `feedback="rewrite section 2"`
- **THEN** the graph SHALL navigate back to `editor_run`
- **AND** the state's `review_feedback` SHALL be `"rewrite section 2"`
- **AND** the editor node's output field SHALL be the empty string when `editor_run` begins executing

#### Scenario: Edit replaces output and proceeds

- **GIVEN** a pipeline paused at `editor_interrupt`
- **WHEN** `resume_pipeline` is invoked with `action="edit"` and `edited="new replacement content"`
- **THEN** the graph state SHALL have the editor node's output field equal to `"new replacement content"`
- **AND** `review_feedback` SHALL be `""`
- **AND** the graph SHALL proceed past the interrupt without re-executing `editor_run`

### Requirement: Export endpoint serves the most recent final_output

`GET /api/runs/{run_id}/export` SHALL return the value of `workflow_runs.metadata.final_output` from the most recent write for the specified run. The endpoint SHALL NOT cache the exported content; repeated calls SHALL read directly from the database (or a cache that is invalidated atomically on every `workflow_runs.metadata` update).

Specifically, after a reject → re-run → approve cycle, the export endpoint SHALL serve the final_output produced by the re-executed node, not a stale value captured before the rejection.

#### Scenario: Export serves latest after reject-rerun-approve

- **GIVEN** a run `run_xyz` that first produced `final_output="draft_v1"` at an interrupt
- **AND** was rejected with feedback, re-ran, and produced `final_output="draft_v2"` at a second interrupt
- **AND** was approved on the second interrupt
- **WHEN** a client issues `GET /api/runs/run_xyz/export`
- **THEN** the response body SHALL contain `"draft_v2"` (or a markdown export derived from it)
- **AND** SHALL NOT contain `"draft_v1"`

#### Scenario: Export is not cached between sequential reads

- **GIVEN** a completed run whose `final_output` was written with value `"A"` and then updated to `"B"` via a resume cycle
- **WHEN** a client issues two sequential `GET /api/runs/{run_id}/export` calls
- **THEN** both responses SHALL contain `"B"`
- **AND** neither response SHALL contain `"A"` from a stale cache

