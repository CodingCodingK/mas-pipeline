## 1. Resolver business layer

- [x] 1.1 Create `src/storage/__init__.py` re-exporting the public API
- [x] 1.2 Create `src/storage/layered.py`:
  - Module-level `_ROOT` computed from `__file__` (overridable by tests via monkey-patch)
  - `_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")`, `_safe_name(name)` raises `ValueError`
  - `_global_dir(kind)`, `_project_dir(kind, project_id)` helpers
  - `class StorageError(Exception)`, `class InvalidNameError(StorageError, ValueError)`, `class AgentInUseError(StorageError)` (holds `.references: list[dict]`)
  - Agent resolvers: `resolve_agent_file(name, project_id) -> Path`, `read_agent(name, project_id) -> str`, `list_agents_global() -> list[str]`, `list_agents_project(project_id) -> list[str]`, `merged_agents_view(project_id) -> list[dict]`, `write_agent_global(name, content) -> bool` (returns True if created new), `write_agent_project(name, project_id, content) -> bool`, `delete_agent_global(name) -> None` (raises `AgentInUseError` if refs found), `delete_agent_project(name, project_id) -> None`
  - Pipeline resolvers: mirror of agent set, except global layer falls back to `{name}_generation.yaml` inside `resolve_pipeline_file`; no reference check on delete
  - Reference scanner `find_agent_references_global(agent_name) -> list[dict]`:
    - Scans `pipelines/*.yaml` + `projects/*/pipelines/*.yaml`
    - For project pipelines, skips projects with their own `agents/<name>.md` override
    - Uses `_extract_roles_from_pipeline(path) -> set[str]` which reads `data["nodes"][*]["role"]`, tolerates malformed yaml
    - Project dir name must parse as `int(dir.name)`; non-numeric dirs are skipped

## 2. Engine integration

- [x] 2.1 Modify `src/agent/factory.py`:
  - Replace `role_path = _AGENTS_DIR / f"{role}.md"` with `role_path = resolve_agent_file(role, project_id)`
  - Remove the now-unused `_AGENTS_DIR` constant (or keep it for now if other code imports it — verify with grep)
  - The existing `FileNotFoundError` raised by the resolver satisfies the same contract
- [x] 2.2 Modify `src/engine/pipeline.py`:
  - Find 3 sites doing `_PIPELINES_DIR / f"{name}.yaml"` — replace with `resolve_pipeline_file(name, project_id=<threaded in>)`
  - Thread `run.project_id` through `execute_pipeline` / `resume_pipeline` internal call paths
  - Remove `_PIPELINES_DIR` if unused
- [x] 2.3 Modify `src/api/runs.py`:
  - Replace `_pipeline_yaml_path(name)` with `resolve_pipeline_file(name, project_id)` — project_id is already a path param in the POST run handler
  - Remove `_PIPELINES_DIR` + `_pipeline_yaml_path` helper

## 3. REST — agents

- [x] 3.1 Create `src/api/agents.py`:
  - `router = APIRouter(dependencies=[Depends(require_api_key)])`
  - Pydantic models: `AgentContent(BaseModel) { content: str }`, `AgentItem(BaseModel) { name: str; source: str | None = None }`, `AgentListResponse(BaseModel) { items: list[AgentItem] }`, `AgentReadResponse(BaseModel) { name: str; content: str; source: str | None = None }`, `AgentReferencesResponse(BaseModel) { detail: str; references: list[dict] }`
  - Global routes:
    - `GET /agents` → list global (source always "global")
    - `GET /agents/{name}` → read global file content
    - `PUT /agents/{name}` body `AgentContent` → write global, 201 on create / 200 on update
    - `DELETE /agents/{name}` → 204 on success, 409 with `AgentReferencesResponse` if in use
  - Project routes:
    - `GET /projects/{project_id}/agents` → merged view
    - `GET /projects/{project_id}/agents/{name}` → read effective (resolver), include `source`
    - `PUT /projects/{project_id}/agents/{name}` body `AgentContent` → write project layer
    - `DELETE /projects/{project_id}/agents/{name}` → 204 (removes override only)
  - Exception mapping:
    - `InvalidNameError` → 422
    - `FileNotFoundError` → 404
    - `AgentInUseError` → 409 with structured references

## 4. REST — pipelines

- [x] 4.1 Create `src/api/pipelines.py`:
  - Same shape as agents.py, pipeline extension `.yaml`
  - Pydantic: `PipelineContent { content: str }`, `PipelineItem { name: str; source: str | None }`, `PipelineListResponse`, `PipelineReadResponse`
  - 8 routes, same prefixes as agents
  - DELETE handlers do NOT call any reference scanner; 204 on success, 404 if missing

## 5. Wiring

- [x] 5.1 Modify `src/main.py`:
  - `from src.api.agents import router as agents_router`
  - `from src.api.pipelines import router as pipelines_router`
  - `api_router.include_router(agents_router)` and `api_router.include_router(pipelines_router)` after the export router
- [x] 5.2 Import-check: `python -c "import src.main; print([r.path for r in src.main.app.routes if '/agents' in getattr(r,'path','') or '/pipelines' in getattr(r,'path','')])"`

## 6. Tests

- [x] 6.1 `scripts/test_layered_storage.py` (no PG — uses tmpdir):
  - Monkey-patches `src.storage.layered._ROOT` to a fresh `tempfile.mkdtemp()`
  - Resolver precedence: project override wins, falls back to global, raises on missing
  - Name validation: `..`, `/`, `..\\win`, empty, `a b`, `中文` all rejected
  - Pipeline variant fallback: global `x_generation.yaml` resolves when `x.yaml` absent; project layer does NOT fall back
  - CRUD round-trips: write → read → list → delete for both layers, both kinds
  - Merged view: empty project → all "global"; override → "project-override"; project-only addition → "project-only"
  - Reference scanner: detects global pipeline ref, detects project pipeline ref, skips project with own agent override, handles malformed yaml, handles non-numeric project dir name
  - `delete_agent_global` raises `AgentInUseError` with populated `references`
  - `delete_agent_project` on non-existent raises `FileNotFoundError`
- [x] 6.2 `scripts/test_rest_agents.py` (no PG — tmpdir + TestClient):
  - Monkey-patches `_ROOT` + disables auth via `patch("src.api.auth.get_settings")`
  - `PUT /api/agents/alpha` with body → 201; second PUT → 200
  - `GET /api/agents` → items includes alpha
  - `GET /api/agents/alpha` → body equals content
  - `PUT /api/projects/1/agents/alpha` → 201 (override)
  - `GET /api/projects/1/agents` → alpha source=project-override
  - `GET /api/projects/1/agents/alpha` → returns project content
  - `DELETE /api/projects/1/agents/alpha` → 204; GET again → returns global content
  - `DELETE /api/agents/alpha` with no pipeline ref → 204
  - `DELETE /api/agents/writer` where a global pipeline references it → 409 with references list
  - 422 for `PUT /api/agents/..` (name validation)
  - 401 when api_keys non-empty and header missing
- [x] 6.3 `scripts/test_rest_pipelines.py` (no PG — tmpdir):
  - Same matrix as agents, minus the reference-check case
  - Pipeline delete always 204/404, never 409

## 7. Validate + progress

- [x] 7.1 `openspec validate add-agent-pipeline-layered-storage --strict`
- [x] 7.2 Update `.plan/progress.md` — Phase 6.4 step 4 entry
- [x] 7.3 Archive + commit
