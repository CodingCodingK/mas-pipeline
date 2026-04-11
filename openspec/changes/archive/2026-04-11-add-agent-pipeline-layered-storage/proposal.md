## Why

Phase 6.4 step 1 wired `/api/projects/{id}/files/...` but agents and pipelines are still globally scoped: every project shares the same `agents/*.md` and `pipelines/*.yaml`. Customizing a role (e.g. project-specific writer tone) means forking the repo. The web frontend plan (step 3) needs to render a merged view — "this agent is inherited from global, this one is overridden by the project" — which requires a layered resolver at the file-system level.

CC's convention is the blueprint: global `agents/*.md` + project-layer `projects/<id>/agents/*.md`, project wins. Zero migration — the existing `agents/` and `pipelines/` directories are literally the global layer as-is. No new database table, no YAML schema change, no engine wiring rewrite.

## What Changes

1. **Resolver business layer** (`src/storage/layered.py`): generic functions for agents and pipelines — `resolve_agent_file(name, project_id) → Path`, `resolve_pipeline_file(name, project_id) → Path`, plus read/write/delete/list/merged-view primitives. Name validation `[A-Za-z0-9_-]+` rejects path traversal. Project layer uses strict `<name>.ext` (no variant fallback); global layer keeps its existing `<name>_generation.yaml` fallback for backward compat.
2. **Engine integration** (`src/agent/factory.py`, `src/engine/pipeline.py`, `src/api/runs.py`): replace hardcoded `_AGENTS_DIR / f"{role}.md"` and `_PIPELINES_DIR / f"{name}.yaml"` with resolver calls. `create_agent` already takes `project_id` — just pass it through. Engine pipeline execution threads `run.project_id` into `load_pipeline` via the resolver.
3. **REST endpoints — agents** (`src/api/agents.py`): 4 global + 4 project routes, symmetric. `PUT` is idempotent upsert (no separate POST). DELETE on the global layer does a reference check: scans all pipeline yaml files for `nodes[].role == <name>`, skipping projects that have their own override; if references exist, returns 409 + list of blockers.
4. **REST endpoints — pipelines** (`src/api/pipelines.py`): mirror of agents, but DELETE does **not** do a reference check (pipeline references are runtime-only, not static). 8 routes total.
5. **Wiring** (`src/main.py`): mount both routers under `/api`.
6. **Tests** (no PG — tmpdir + monkey-patch `_ROOT`):
   - `scripts/test_layered_storage.py` — resolver precedence, name validation, reference scanner, merged view
   - `scripts/test_rest_agents.py` — 8 routes × happy path + 401/404/409/422
   - `scripts/test_rest_pipelines.py` — 8 routes × happy path

## Impact

**Affected code**:
- NEW: `src/storage/__init__.py`, `src/storage/layered.py`, `src/api/agents.py`, `src/api/pipelines.py`
- MODIFIED: `src/agent/factory.py` (1 line), `src/engine/pipeline.py` (3 call sites), `src/api/runs.py` (1 helper), `src/main.py` (imports + 2 mounts)
- NEW tests: 3 scripts

**Affected specs**:
- NEW capability `agent-storage`
- NEW capability `pipeline-storage`

**Backward compatibility**:
- `create_agent(role, project_id=None)` with no project_id keeps old behavior (global only).
- `runs.py::_pipeline_yaml_path` preserves `<name>_generation.yaml` fallback inside the resolver (scoped to global layer).
- Existing `agents/*.md` and `pipelines/*.yaml` become the global layer with zero edits. No migration script.
- No new DB tables or columns.

**Out of scope**:
- Database-backed agent/pipeline storage (files are enough; CC does it this way)
- Content validation beyond what `parse_role_file` / `load_pipeline` already do
- Version history or diff views (git is the version store)
- Soft delete or `.deleted` suffix (unix rm semantics, decision 2-A was rejected in favor of 2-B reference check)
- Coordinator `spawn_agent` dynamic references (string-only, can't statically extract — documented as a known gap)
- Front-end UI (Change 3)
