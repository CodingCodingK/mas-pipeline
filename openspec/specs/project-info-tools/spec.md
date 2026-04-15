# project-info-tools Specification

## Purpose
TBD - created by archiving change add-project-info-tools. Update Purpose after archive.
## Requirements
### Requirement: get_current_project tool
The system SHALL provide a built-in read-only tool named `get_current_project` that takes no parameters and returns the current project's metadata. This tool is distinct from clawbot's existing `get_project_info` (which takes an explicit `project_id` parameter and describes a project the caller may not own); the two tools coexist in the built-in pool.

The tool SHALL live at `src/tools/builtins/project_info.py`, SHALL declare `is_read_only() → True` and `is_concurrency_safe() → True`, and SHALL be registered in `src/tools/builtins/__init__.py:get_all_tools()`.

The tool SHALL resolve the project from `ToolContext.project_id`. If `context.project_id` is `None`, the tool SHALL return `ToolResult(success=False, output="Error: no project context available")` without querying the database.

On success, the output SHALL be a plain-text block containing, in order:
- `project_id`
- `name`
- `pipeline` (the pipeline binding from `projects.pipeline`)
- `description` (if present, otherwise omitted)
- `document_count` (COUNT from `documents` where `project_id = ctx.project_id`)
- `latest_run`: one line with `run_id`, `status`, and `started_at` of the most recent `workflow_runs` row for this project (by `started_at DESC NULLS LAST, id DESC`); or the literal string `(none)` if no runs exist.

#### Scenario: Successful fetch
- **WHEN** an agent with `project_id=42` calls `get_current_project`
- **THEN** the tool SHALL run a query against `projects`, `documents`, and `workflow_runs` scoped to project 42
- **AND** the output SHALL include all six fields listed above
- **AND** the tool SHALL NOT expose data from any other project

#### Scenario: Missing project context
- **WHEN** `ToolContext.project_id` is `None` at call time
- **THEN** the tool SHALL return `ToolResult(success=False, output="Error: no project context available")`
- **AND** no database query SHALL be issued

#### Scenario: Project has no runs
- **WHEN** the project has zero rows in `workflow_runs`
- **THEN** the `latest_run` line SHALL be the literal string `(none)`
- **AND** the tool SHALL still succeed

---

### Requirement: list_project_runs tool
The system SHALL provide a built-in read-only tool named `list_project_runs` that returns a chronologically descending list of recent workflow runs for the current project.

The tool's `input_schema` SHALL declare two optional parameters:
- `limit: int` — maximum number of runs to return. Default `10`. Values outside `[1, 50]` SHALL be clamped to that range.
- `status: str` — optional exact-match filter on `workflow_runs.status`. When omitted, all statuses are included.

The tool SHALL query `SELECT id, run_id, pipeline, status, started_at, finished_at FROM workflow_runs WHERE project_id = :ctx_pid [AND status = :status] ORDER BY started_at DESC NULLS LAST, id DESC LIMIT :limit`.

The output SHALL be a plain-text block with one line per run: `run_id | pipeline | status | started_at | duration_s`. `duration_s` SHALL be computed from `finished_at - started_at` when both are present, otherwise the literal `-`. If zero runs match, the output SHALL be the literal string `(no runs)` with `success=True`.

#### Scenario: Default call returns latest 10 runs
- **WHEN** an agent calls `list_project_runs` with no arguments
- **THEN** up to 10 rows SHALL be returned, ordered newest first
- **AND** all rows SHALL satisfy `project_id = context.project_id`

#### Scenario: Status filter
- **WHEN** an agent calls `list_project_runs` with `status="failed"`
- **THEN** only runs with `status='failed'` in the current project SHALL be returned

#### Scenario: Limit clamping
- **WHEN** an agent calls `list_project_runs` with `limit=500`
- **THEN** the tool SHALL clamp to `50` before querying
- **AND** at most 50 rows SHALL be returned

#### Scenario: No project context
- **WHEN** `ToolContext.project_id` is `None`
- **THEN** the tool SHALL return `ToolResult(success=False, output="Error: no project context available")`

---

### Requirement: get_run_details tool
The system SHALL provide a built-in read-only tool named `get_run_details` that returns the per-node breakdown of a single workflow run.

The tool's `input_schema` SHALL declare one required parameter:
- `run_id: str` — the string run identifier (matches `workflow_runs.run_id`, not the numeric primary key).

The tool SHALL look up the run via `SELECT id, pipeline, status, started_at, finished_at FROM workflow_runs WHERE run_id = :rid AND project_id = :ctx_pid`. If the row is missing (either the run does not exist at all, or it belongs to a different project), the tool SHALL return `ToolResult(success=False, output="Error: run '<rid>' not found in current project")`. The tool SHALL NOT distinguish between "missing" and "wrong project" in its output.

On success, the tool SHALL also fetch all `agent_runs` rows where `agent_runs.run_id = workflow_runs.id`, ordered by `id ASC`, and for each row produce a one-line summary: `role | status | tool_use_count | total_tokens | duration_ms | preview`.

`preview` SHALL be derived by:
1. Scanning the `agent_runs.messages` JSONB array for the last element with `role == "assistant"` and extracting its text content;
2. If no assistant message exists, falling back to `agent_runs.result`;
3. If both are empty, falling back to the literal `(no output)`;
4. Truncating the result to 200 characters with a trailing ellipsis if truncated.

The overall output SHALL be a plain-text block containing the workflow-level summary (run_id, pipeline, status, duration) followed by the list of node lines, or the literal string `(no nodes)` if `agent_runs` is empty for this run.

#### Scenario: Successful fetch of a run in the current project
- **WHEN** an agent with `project_id=42` calls `get_run_details(run_id="run-abc")` and `run-abc` is a run in project 42 with 3 agent_runs
- **THEN** the output SHALL contain one workflow-level summary line and 3 node lines
- **AND** each node line SHALL contain role / status / tool_use_count / total_tokens / duration_ms / preview

#### Scenario: Cross-project run is rejected as not-found
- **WHEN** an agent with `project_id=42` calls `get_run_details(run_id="run-xyz")` where `run-xyz` exists but belongs to `project_id=99`
- **THEN** the tool SHALL return `ToolResult(success=False, output="Error: run 'run-xyz' not found in current project")`
- **AND** the tool SHALL NOT reveal that the run exists
- **AND** no `agent_runs` query SHALL execute

#### Scenario: Run with no agent_runs
- **WHEN** a run exists in the current project but has zero `agent_runs` rows
- **THEN** the workflow-level summary SHALL be returned
- **AND** the node-list section SHALL be the literal string `(no nodes)`

#### Scenario: Preview falls back to result when assistant message is absent
- **WHEN** an `agent_runs` row has `messages=[]` but `result="Done in 3 steps"`
- **THEN** the preview SHALL be `Done in 3 steps`

#### Scenario: Preview truncates at 200 characters
- **WHEN** an assistant message is 500 characters long
- **THEN** the preview SHALL contain the first 200 characters plus a trailing `…` or `...` ellipsis marker
- **AND** total preview length SHALL NOT exceed 204 characters

#### Scenario: No project context
- **WHEN** `ToolContext.project_id` is `None`
- **THEN** the tool SHALL return `ToolResult(success=False, output="Error: no project context available")`
- **AND** no database query SHALL execute

---

### Requirement: Tool registration and agent grants
The three tools defined above SHALL be registered in `src/tools/builtins/__init__.py:get_all_tools()` alongside the existing built-ins.

The frontmatter `tools:` list of `agents/assistant.md`, `agents/coordinator.md`, and `agents/clawbot.md` SHALL include `get_current_project`, `list_project_runs`, and `get_run_details`. Pipeline sub-role agents (researcher, writer, reviewer, parser, etc.) SHALL NOT receive these tools.

#### Scenario: Assistant holds all three tools
- **WHEN** `agents/assistant.md` is loaded at Gateway startup
- **THEN** its resolved tool set SHALL include `get_current_project`, `list_project_runs`, and `get_run_details`

#### Scenario: Coordinator holds all three tools
- **WHEN** `agents/coordinator.md` is loaded
- **THEN** its resolved tool set SHALL include `get_current_project`, `list_project_runs`, and `get_run_details`

#### Scenario: Clawbot holds all three tools
- **WHEN** `agents/clawbot.md` is loaded
- **THEN** its resolved tool set SHALL include `get_current_project`, `list_project_runs`, and `get_run_details`

#### Scenario: Pipeline sub-role does not receive project-info tools
- **WHEN** a pipeline sub-role file (e.g. `agents/writer.md`) does not list these tools in its frontmatter
- **THEN** calls to them from that role's agent loop SHALL fail with the standard "tool not available" path

