# agent-storage Specification

## Purpose
TBD - created by archiving change add-agent-pipeline-layered-storage. Update Purpose after archive.
## Requirements
### Requirement: Two-layer agent file storage with project override

The system SHALL store agent role files on disk in two layers:

- **Global layer**: `agents/<name>.md` (pre-existing directory — becomes the global layer as-is, no migration)
- **Project layer**: `projects/<project_id>/agents/<name>.md` (created lazily on first write)

`src.storage.layered.resolve_agent_file(name: str, project_id: int | None) -> Path` SHALL resolve an agent name to its effective file path. When `project_id` is provided and `projects/<project_id>/agents/<name>.md` exists, that path SHALL be returned. Otherwise the function SHALL return `agents/<name>.md` if it exists. If neither exists, the function SHALL raise `FileNotFoundError`.

#### Scenario: Project override wins over global

- **GIVEN** `agents/writer.md` exists with content A
- **AND** `projects/42/agents/writer.md` exists with content B
- **WHEN** `resolve_agent_file("writer", 42)` is called
- **THEN** the returned path SHALL be `projects/42/agents/writer.md`

#### Scenario: Falls back to global when project override absent

- **GIVEN** `agents/writer.md` exists
- **AND** `projects/42/agents/writer.md` does NOT exist
- **WHEN** `resolve_agent_file("writer", 42)` is called
- **THEN** the returned path SHALL be `agents/writer.md`

#### Scenario: project_id=None uses global only

- **GIVEN** `agents/writer.md` exists
- **WHEN** `resolve_agent_file("writer", None)` is called
- **THEN** the returned path SHALL be `agents/writer.md`

#### Scenario: Missing agent raises FileNotFoundError

- **GIVEN** neither `agents/nobody.md` nor `projects/1/agents/nobody.md` exists
- **WHEN** `resolve_agent_file("nobody", 1)` is called
- **THEN** a `FileNotFoundError` SHALL be raised

### Requirement: Name validation rejects path traversal

Agent names passed to any resolver, CRUD, or REST function SHALL be validated against the regex `^[A-Za-z0-9_-]+$` (full match). Invalid names SHALL cause `InvalidNameError` (a subclass of both `StorageError` and `ValueError`) to be raised before any filesystem access.

#### Scenario: Rejects path traversal attempts

- **WHEN** `resolve_agent_file("..", None)` is called
- **THEN** `InvalidNameError` SHALL be raised
- **AND** no filesystem I/O SHALL have been performed

#### Scenario: Rejects slashes and dots

- **WHEN** any of `"a/b"`, `"a.b"`, `"a b"`, `""`, `"中文"` is passed as a name
- **THEN** `InvalidNameError` SHALL be raised

#### Scenario: Accepts alphanumerics, underscore, hyphen

- **WHEN** `"writer_v2"`, `"Agent-1"`, `"abc"` are passed as names
- **THEN** no exception SHALL be raised for validation

### Requirement: CRUD operations on both layers

The storage module SHALL expose the following operations:

- `read_agent(name, project_id) -> str` — returns the text content of the effective file (uses resolver)
- `list_agents_global() -> list[str]` — returns sorted stems of `agents/*.md`
- `list_agents_project(project_id) -> list[str]` — returns sorted stems of `projects/<pid>/agents/*.md`
- `write_agent_global(name, content) -> bool` — writes `agents/<name>.md`, returns True if newly created, False if overwritten
- `write_agent_project(name, project_id, content) -> bool` — writes `projects/<pid>/agents/<name>.md`, creating parent directories as needed
- `delete_agent_project(name, project_id) -> None` — unlinks `projects/<pid>/agents/<name>.md`, raises `FileNotFoundError` if missing
- `delete_agent_global(name) -> None` — scans references (see below); raises `AgentInUseError` if referenced, otherwise unlinks

All operations SHALL validate `name` via the name-validation rule above.

#### Scenario: write_agent_project creates parent directories

- **GIVEN** `projects/99/` does not yet exist
- **WHEN** `write_agent_project("test", 99, "hello")` is called
- **THEN** `projects/99/agents/test.md` SHALL exist with content `"hello"`

#### Scenario: write returns True on create, False on overwrite

- **WHEN** `write_agent_global("new", "x")` is called for the first time
- **THEN** the return value SHALL be `True`
- **WHEN** the same call is repeated
- **THEN** the return value SHALL be `False`

#### Scenario: list is sorted and excludes extensions

- **GIVEN** `agents/` contains `zeta.md`, `alpha.md`, `mid.md`
- **WHEN** `list_agents_global()` is called
- **THEN** the return value SHALL be `["alpha", "mid", "zeta"]`

### Requirement: Merged view classifies agents by source

`merged_agents_view(project_id) -> list[dict]` SHALL return the union of global and project layer agent names, annotated with a `source` field whose value is one of:

- `"global"` — exists only in the global layer
- `"project-only"` — exists only in the project layer
- `"project-override"` — exists in both layers (project layer wins at resolve time)

The list SHALL be sorted by name ascending. Each item SHALL be a dict with keys `name` (str) and `source` (str).

#### Scenario: Three-state classification

- **GIVEN** `agents/` contains `writer.md` and `researcher.md`
- **AND** `projects/42/agents/` contains `writer.md` (override) and `analyst.md` (project-only)
- **WHEN** `merged_agents_view(42)` is called
- **THEN** the result SHALL equal `[{"name": "analyst", "source": "project-only"}, {"name": "researcher", "source": "global"}, {"name": "writer", "source": "project-override"}]`

### Requirement: Delete-global reference check

`delete_agent_global(name)` SHALL scan pipeline YAML files for static references to the agent before deletion. The scan SHALL:

1. Enumerate `pipelines/*.yaml`. Parse each file's `nodes[].role` field. If `name` appears, record `{"project_id": None, "pipeline": <filename stem>, "role": name}`.
2. For each subdirectory of `projects/` whose name parses as an integer: if `projects/<id>/agents/<name>.md` exists, skip (the project has its own override and is unaffected by global deletion). Otherwise, enumerate `projects/<id>/pipelines/*.yaml` and record references.
3. If any references were recorded, raise `AgentInUseError` with the full list as its `.references` attribute. Do NOT unlink.
4. If no references were recorded, unlink the file.

Malformed pipeline YAML (raises during `yaml.safe_load`, or returns a non-dict, or has no `nodes` list) SHALL contribute zero references and SHALL NOT cause the scan itself to fail.

Non-numeric directory names under `projects/` SHALL be skipped silently.

The reference check SHALL NOT scan coordinator prompts, skill files, or `spawn_agent` tool arguments — those are runtime-dynamic references and are documented as a known gap.

#### Scenario: Global pipeline referencing agent blocks global delete

- **GIVEN** `agents/writer.md` exists
- **AND** `pipelines/blog.yaml` has a node with `role: writer`
- **WHEN** `delete_agent_global("writer")` is called
- **THEN** `AgentInUseError` SHALL be raised
- **AND** its `.references` SHALL contain `{"project_id": None, "pipeline": "blog", "role": "writer"}`
- **AND** `agents/writer.md` SHALL still exist afterwards

#### Scenario: Project override shields the project's pipelines

- **GIVEN** `agents/writer.md` exists
- **AND** `projects/42/agents/writer.md` exists (override)
- **AND** `projects/42/pipelines/blog.yaml` has a node with `role: writer`
- **AND** no other project or global pipeline references `writer`
- **WHEN** `delete_agent_global("writer")` is called
- **THEN** the global file SHALL be unlinked successfully
- **AND** no `AgentInUseError` SHALL be raised
- **AND** `projects/42/agents/writer.md` SHALL still exist afterwards

#### Scenario: Project without override blocks global delete

- **GIVEN** `agents/writer.md` exists
- **AND** `projects/42/agents/writer.md` does NOT exist
- **AND** `projects/42/pipelines/blog.yaml` has a node with `role: writer`
- **WHEN** `delete_agent_global("writer")` is called
- **THEN** `AgentInUseError` SHALL be raised with `references` containing `{"project_id": 42, "pipeline": "blog", "role": "writer"}`

#### Scenario: Malformed pipeline yaml is tolerated

- **GIVEN** `pipelines/broken.yaml` contains invalid YAML
- **AND** no other pipeline references `writer`
- **WHEN** `delete_agent_global("writer")` is called
- **THEN** the delete SHALL succeed (broken file contributes zero references)

#### Scenario: Delete project-layer override

- **GIVEN** `projects/42/agents/writer.md` exists
- **WHEN** `delete_agent_project("writer", 42)` is called
- **THEN** the file SHALL be unlinked
- **AND** no reference check SHALL be performed (the global version remains and takes over)

### Requirement: Agent REST endpoints

The system SHALL expose REST endpoints under `/api` registered on the same router chain as the Phase 6.1/6.3/6.4 routes, behind `require_api_key`:

**Global layer**:
- `GET /api/agents` → 200, `{"items": [{"name": str, "source": "global"}, ...]}` sorted by name
- `GET /api/agents/{name}` → 200, `{"name": str, "content": str, "source": "global"}`; 404 if missing; 422 if name invalid
- `PUT /api/agents/{name}` body `{"content": str}` → 201 on create, 200 on overwrite; 422 on invalid name or missing content
- `DELETE /api/agents/{name}` → 204 on success; 404 if missing; 409 with `{"detail": str, "references": list}` if `AgentInUseError` raised

**Project layer**:
- `GET /api/projects/{project_id}/agents` → 200, `{"items": [{"name", "source"}, ...]}` merged view
- `GET /api/projects/{project_id}/agents/{name}` → 200, `{"name", "content", "source"}` where `source` is the effective source from resolve; 404 if missing
- `PUT /api/projects/{project_id}/agents/{name}` body `{"content": str}` → 201 on create, 200 on overwrite
- `DELETE /api/projects/{project_id}/agents/{name}` → 204 on success; 404 if the project-layer file does not exist

All endpoints SHALL require the `X-API-Key` header when `settings.api_keys` is non-empty.

#### Scenario: PUT is idempotent upsert

- **WHEN** `PUT /api/agents/alpha` with `{"content": "hello"}` is called for the first time
- **THEN** the response status SHALL be 201
- **AND** a subsequent identical `PUT` SHALL return status 200

#### Scenario: DELETE global with references returns 409 + list

- **GIVEN** `pipelines/blog.yaml` has a node with `role: writer`
- **WHEN** `DELETE /api/agents/writer` is called
- **THEN** the response status SHALL be 409
- **AND** the body SHALL be `{"detail": "agent 'writer' is referenced by 1 pipeline(s)", "references": [{"project_id": null, "pipeline": "blog", "role": "writer"}]}`

#### Scenario: Invalid name returns 422

- **WHEN** `PUT /api/agents/..` is called
- **THEN** the response status SHALL be 422

#### Scenario: DELETE project removes only the override

- **GIVEN** `agents/writer.md` and `projects/42/agents/writer.md` both exist
- **WHEN** `DELETE /api/projects/42/agents/writer` is called
- **THEN** the response status SHALL be 204
- **AND** `GET /api/projects/42/agents/writer` SHALL subsequently return 200 with `source="global"` and the global file's content

