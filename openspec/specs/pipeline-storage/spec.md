# pipeline-storage Specification

## Purpose
TBD - created by archiving change add-agent-pipeline-layered-storage. Update Purpose after archive.
## Requirements
### Requirement: Two-layer pipeline file storage with project override

The system SHALL store pipeline YAML files on disk in two layers:

- **Global layer**: `pipelines/<name>.yaml` (pre-existing directory)
- **Project layer**: `projects/<project_id>/pipelines/<name>.yaml` (created lazily on first write)

`src.storage.layered.resolve_pipeline_file(name: str, project_id: int | None) -> Path` SHALL resolve a pipeline name to its effective file path. The resolution order is:

1. If `project_id` is not None, try `projects/<project_id>/pipelines/<name>.yaml`
2. Try `pipelines/<name>.yaml` (global, strict name)
3. Try `pipelines/<name>_generation.yaml` (global, legacy variant — preserves `src.api.runs._pipeline_yaml_path` backward compatibility)
4. Raise `FileNotFoundError` if all three miss

The project layer SHALL NOT apply the `_generation` variant fallback. Project pipelines MUST be named exactly `<name>.yaml`.

#### Scenario: Project override wins

- **GIVEN** `pipelines/blog_generation.yaml` and `projects/7/pipelines/blog.yaml` both exist
- **WHEN** `resolve_pipeline_file("blog", 7)` is called
- **THEN** the returned path SHALL be `projects/7/pipelines/blog.yaml`

#### Scenario: Global variant fallback for legacy pipelines

- **GIVEN** `pipelines/blog.yaml` does NOT exist
- **AND** `pipelines/blog_generation.yaml` exists
- **AND** no project override exists
- **WHEN** `resolve_pipeline_file("blog", None)` is called
- **THEN** the returned path SHALL be `pipelines/blog_generation.yaml`

#### Scenario: Project layer does not apply variant fallback

- **GIVEN** `projects/7/pipelines/blog.yaml` does NOT exist
- **AND** `projects/7/pipelines/blog_generation.yaml` exists
- **AND** `pipelines/blog.yaml` exists
- **WHEN** `resolve_pipeline_file("blog", 7)` is called
- **THEN** the returned path SHALL be `pipelines/blog.yaml` (the project-layer variant file is ignored; resolver falls through to global)

#### Scenario: Missing pipeline raises FileNotFoundError

- **GIVEN** no matching file exists in any layer
- **WHEN** `resolve_pipeline_file("nobody", 1)` is called
- **THEN** `FileNotFoundError` SHALL be raised

### Requirement: Pipeline name validation

Pipeline names SHALL be validated against the same regex `^[A-Za-z0-9_-]+$` as agent names. Invalid names raise `InvalidNameError` before any filesystem access.

#### Scenario: Path traversal rejected

- **WHEN** `resolve_pipeline_file("../etc/passwd", None)` is called
- **THEN** `InvalidNameError` SHALL be raised

### Requirement: CRUD operations for pipelines

The storage module SHALL expose:

- `read_pipeline(name, project_id) -> str`
- `list_pipelines_global() -> list[str]`
- `list_pipelines_project(project_id) -> list[str]`
- `write_pipeline_global(name, content) -> bool`
- `write_pipeline_project(name, project_id, content) -> bool`
- `delete_pipeline_global(name) -> None` — raises `FileNotFoundError` if missing; NO reference check
- `delete_pipeline_project(name, project_id) -> None` — raises `FileNotFoundError` if missing
- `merged_pipelines_view(project_id) -> list[dict]` with the same three-state source classification as agents

Unlike agent deletion, pipeline deletion SHALL NOT perform any reference scanning. Pipelines are not statically referenced by any other file in the repository; runtime references (active `WorkflowRun` rows, REST calls) are the caller's concern.

#### Scenario: Pipeline delete is unconditional

- **GIVEN** `pipelines/blog.yaml` exists
- **WHEN** `delete_pipeline_global("blog")` is called
- **THEN** the file SHALL be unlinked
- **AND** no scanning SHALL be performed

#### Scenario: Merged view for pipelines

- **GIVEN** `pipelines/` contains `blog.yaml`, `courseware.yaml`
- **AND** `projects/5/pipelines/` contains `blog.yaml` (override), `internal.yaml` (project-only)
- **WHEN** `merged_pipelines_view(5)` is called
- **THEN** the result SHALL contain 3 items: `blog` (project-override), `courseware` (global), `internal` (project-only)

### Requirement: Pipeline REST endpoints

The system SHALL expose REST endpoints under `/api` behind `require_api_key`:

**Global layer**:
- `GET /api/pipelines` → 200, `{"items": [{"name": str, "source": "global"}, ...]}`
- `GET /api/pipelines/{name}` → 200, `{"name": str, "content": str, "source": "global"}`
- `PUT /api/pipelines/{name}` body `{"content": str}` → 201 on create, 200 on overwrite; 422 on invalid name
- `DELETE /api/pipelines/{name}` → 204 on success; 404 if missing (never 409)

**Project layer**:
- `GET /api/projects/{project_id}/pipelines` → 200, merged view
- `GET /api/projects/{project_id}/pipelines/{name}` → 200, effective read; 404 if missing
- `PUT /api/projects/{project_id}/pipelines/{name}` body `{"content": str}` → 201/200
- `DELETE /api/projects/{project_id}/pipelines/{name}` → 204; 404 if the project-layer file does not exist

#### Scenario: Pipeline DELETE never returns 409

- **GIVEN** `pipelines/blog.yaml` exists
- **AND** a `WorkflowRun` row exists with `pipeline='blog'`
- **WHEN** `DELETE /api/pipelines/blog` is called
- **THEN** the response status SHALL be 204
- **AND** the file SHALL be unlinked (runtime references are not checked)

#### Scenario: PUT with invalid name returns 422

- **WHEN** `PUT /api/pipelines/..` is called
- **THEN** the response status SHALL be 422

#### Scenario: GET merged view returns three-state classification

- **GIVEN** the state from the "Merged view for pipelines" scenario above
- **WHEN** `GET /api/projects/5/pipelines` is called with a valid API key
- **THEN** the response status SHALL be 200
- **AND** the body items SHALL include `{"name": "blog", "source": "project-override"}`, `{"name": "courseware", "source": "global"}`, `{"name": "internal", "source": "project-only"}`

### Requirement: Engine integration uses resolver

`src/agent/factory.py::create_agent` SHALL resolve the role file via `resolve_agent_file(role, project_id)` instead of the previously-hardcoded `_AGENTS_DIR / f"{role}.md"`. The `project_id` parameter SHALL be threaded through unchanged; when None, the resolver falls back to the global layer (preserving existing behavior for callers that pre-date the project-scoped path).

`src/engine/pipeline.py::execute_pipeline` and `resume_pipeline` SHALL resolve the pipeline file via `resolve_pipeline_file(pipeline_name, run.project_id)`. `src/api/runs.py` SHALL replace its `_pipeline_yaml_path` helper with a direct call to `resolve_pipeline_file(pipeline_name, project_id)` (project_id is already a path parameter on the run-creation endpoint).

#### Scenario: Pipeline run with project override

- **GIVEN** `pipelines/blog.yaml` contains node `writer` with `role: writer`
- **AND** `projects/42/pipelines/blog.yaml` contains a different node graph
- **WHEN** a pipeline run for project 42 pipeline `blog` is triggered
- **THEN** the engine SHALL load `projects/42/pipelines/blog.yaml`
- **AND** SHALL NOT load `pipelines/blog.yaml`

#### Scenario: Agent resolution during pipeline execution

- **GIVEN** `pipelines/blog.yaml` references `role: writer` in one of its nodes
- **AND** `agents/writer.md` exists globally
- **AND** `projects/42/agents/writer.md` exists (project override)
- **WHEN** the engine executes that node during a run with `project_id=42`
- **THEN** `create_agent` SHALL load `projects/42/agents/writer.md` via the resolver

