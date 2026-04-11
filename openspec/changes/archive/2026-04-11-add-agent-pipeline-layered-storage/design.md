## Context

The existing storage layout is flat and global:

```
agents/
  writer.md        # frontmatter + prompt body
  researcher.md
  ...
pipelines/
  blog_generation.yaml
  courseware_exam.yaml
```

`src/agent/factory.py:66` hardcodes `role_path = _AGENTS_DIR / f"{role}.md"`. `src/engine/pipeline.py` has 3 sites doing `load_pipeline(_PIPELINES_DIR / f"{name}.yaml")`. `src/api/runs.py:69` has a helper `_pipeline_yaml_path(name)` that tries `<name>.yaml` then `<name>_generation.yaml` (historical variant support — users can say "blog" and get "blog_generation").

None of these accept a project scope. `create_agent(role, project_id=...)` already has the parameter plumbed through for tool-context purposes, but it's not used for path resolution. The web frontend plan explicitly calls for a merged per-project view (`/projects/:id/agents` showing global + project-override + project-only). That requires a first-class resolver.

## Decisions

### Decision 1: Single resolver module, generic over kind

**Chosen**: one module `src/storage/layered.py` exposing two public function sets (`resolve_agent_file` / read / write / delete / list / merged_view and the same for pipelines). Not a class, not a generic parametric interface — two concrete function families that share private helpers (`_safe_name`, `_global_dir`, `_project_dir`).

**Alternatives considered**:
- **Class-based `LayeredStorage(kind=...)`**: over-abstracts two things that happen to share 80% of logic but diverge on deletion semantics (agent has reference check, pipeline does not) and file extension.
- **Inline resolver in each caller**: three call sites in `pipeline.py` would end up with copy-pasted `if project_dir.exists() else global_dir` branches.

**Why**: good taste — eliminating the special case goes to a resolver layer, not to a generic abstraction. The two function families diverge just enough that the class form would need an `if self.kind == "agent"` branch for reference-checking, which is exactly the special case we're eliminating.

### Decision 2: File-based, not database-backed

**Chosen**: project-layer files on disk under `projects/<project_id>/{agents,pipelines}/`. No new tables.

**Alternatives considered**:
- **`project_agents` and `project_pipelines` tables**: supports multi-instance deployment, but requires a migration and every REST write becomes a DB transaction + optional disk cache.
- **Blob in `projects.metadata_`**: one row update per write, but poor listing ergonomics and conflates user-editable content with metadata.

**Why**: CC's convention, zero migration, git-observable, works with Monaco editor's raw text round-trip. Multi-instance deployment is explicitly out of scope for Phase 6.4 (single-server install). When we need multi-instance, promote the file store to an S3 or CAS backend — non-breaking.

### Decision 3: Project layer uses strict name, global keeps variant fallback

**Chosen**: 
- `projects/<id>/pipelines/<name>.yaml` — strict. `<name>` must equal the pipeline name exactly.
- Global `pipelines/<name>.yaml` — resolver falls back to `<name>_generation.yaml` if the standard form is missing (preserves `runs.py::_pipeline_yaml_path` semantics).

**Alternatives considered** (1-B): mirror the variant fallback into the project layer. (1-C): hoist the variant fallback out of `runs.py` into the resolver for both layers.

**Why**: 1-A chosen. The `_generation` suffix is historical convention baggage for a handful of pre-existing global pipelines (`blog_generation`, `courseware_exam`). Propagating it to the project layer turns a historical quirk into a permanent part of the public API. Projects are new; they get the clean naming.

**Trade-off**: slight asymmetry between the two layers. Documented in the spec. Users copying a global pipeline to their project layer must rename `blog_generation.yaml` → `blog.yaml` (or `blog_generation.yaml`, either works — strict means "file name equals pipeline name", both forms satisfy that).

### Decision 4: Delete global agent requires reference check (2-B)

**Chosen**: `DELETE /api/agents/{name}` runs a scanner before unlinking:

1. Enumerate all global `pipelines/*.yaml`. Parse yaml, collect `set(node["role"] for node in data["nodes"])`. If `name` is in the set → record `{project_id: None, pipeline: <stem>, role: <name>}`.
2. For each directory under `projects/*/`, skip if `projects/<id>/agents/<name>.md` exists (project has its own override — global deletion doesn't affect it). Otherwise enumerate `projects/<id>/pipelines/*.yaml` and scan.
3. If any references found → 409 with JSON `{"detail": "...", "references": [...]}`.
4. Otherwise `unlink()`.

**Alternatives considered**:
- **No check (2-A)**: simpler, matches unix `rm` semantics. Rejected: user explicitly chose safety over rm-like behavior.
- **Soft delete (2-C)**: rename to `<name>.md.deleted`, resolver ignores. Rejected: introduces a new file state and a special case in the resolver.

**Scope of the scanner**:
- Scans only `nodes[].role` in yaml (static references).
- Does **not** scan coordinator prompts or `spawn_agent` tool calls — those are string arguments at runtime, can't be statically determined. Documented as known gap.
- DELETE on the **project** layer never does a reference check — it only removes the override, so the resolver falls back to the global version. The global version still exists (we scanned it at project-delete-time and found it). This is safe by construction.

### Decision 5: DELETE project layer just removes the override

**Chosen**: `DELETE /api/projects/{pid}/agents/{name}` unlinks `projects/<pid>/agents/<name>.md` only. The resolver immediately starts returning the global version. No reference check.

**Why**: symmetric with the layered semantics — removing an override is always safe. If the global layer also doesn't have it, the next `create_agent("name", project_id=pid)` call will `FileNotFoundError`, but that's already the existing behavior before the project override was added.

### Decision 6: Pipeline DELETE has no reference check (asymmetry justified)

**Chosen**: neither global nor project pipeline delete scans for references.

**Why**: pipelines are only referenced by:
1. **Runtime**: `POST /api/projects/<id>/pipelines/<name>/runs` — if the file is missing, the request 404s. Existing behavior.
2. **In-flight `WorkflowRun` rows**: their `pipeline` column is a string, and the run is already in memory (or resumable from `graph.checkpoint`). Deleting the file affects only `resume_pipeline` calls for paused runs. That's a real edge case but the user can always paste the old yaml back. Not worth a scanner.
3. **Other pipelines**: pipeline yaml doesn't reference other pipelines — no nested includes.

Asymmetry is fine because the *relationship* is asymmetric: pipelines reference agents (static, scannable), but nothing statically references pipelines.

### Decision 7: Name validation `[A-Za-z0-9_-]+`

**Chosen**: regex fullmatch. Rejected characters include `/`, `\`, `.`, space, `..`, empty string.

**Why**: prevents path traversal (the attack: `PUT /api/agents/../../etc/passwd`). Matches the character class already in `src/export/exporter.py::_sanitize_filename_part`. Consistent across the codebase.

**Trade-off**: users can't create `agent名字.md` with Chinese characters. Consistent with CC — role names are identifiers, not display strings. Prompts/descriptions inside the file can be any UTF-8.

### Decision 8: PUT is idempotent upsert, no POST

**Chosen**: `PUT /api/agents/{name}` creates or overwrites. No `POST /api/agents`.

**Why**: agent/pipeline files are content-addressed by name. Create-vs-update is a UI concept that doesn't affect storage semantics — the backend writes bytes to a named path either way. A single idempotent verb is simpler for retries and matches the Monaco editor's "save" action.

**HTTP status codes**:
- `PUT` on new file → 201
- `PUT` on existing file → 200
- `PUT` with invalid name → 422
- `PUT` with body missing `content` field → 422

### Decision 9: Merged view returns three-state source classification

**Chosen**: `GET /api/projects/{pid}/agents` returns:

```json
{"items": [
  {"name": "writer", "source": "project-override"},   // exists in both
  {"name": "analyst", "source": "project-only"},      // exists only in project layer
  {"name": "researcher", "source": "global"}          // exists only in global layer
]}
```

**Why**: matches the web frontend plan's three badges on the Agents page — [全局], [项目覆盖], [项目专属]. The resolver already computes this state implicitly; exposing it as a dedicated field saves the client from a double round-trip.

### Decision 10: Reference scanner tolerates malformed yaml

**Chosen**: if `yaml.safe_load` raises or returns non-dict, treat that pipeline as contributing zero references. Log at warning level.

**Why**: a broken pipeline yaml shouldn't block agent deletion. The broken pipeline is already broken regardless of whether the agent exists. This is pragmatism — don't let bad data in one place cascade into blocking unrelated operations.

## Risks / Trade-offs

- **Scanner cost**: per-delete, we enumerate `pipelines/` + `projects/*/pipelines/`. At 100 projects × 10 pipelines each = 1000 file reads. Acceptable for an admin-scoped delete operation. If it becomes a hotspot, add a reverse index — but premature today.
- **Project ID type**: URL path is `/api/projects/{pid}/...` where `pid` is `int`. If a malformed path like `/api/projects/abc/agents` comes in, FastAPI's path param validation 422s before reaching the handler. Good.
- **Concurrent writes**: two `PUT`s to the same file race on the filesystem. Last-writer-wins. Acceptable for admin-edited content; no locking added.
- **Pipeline yaml without `nodes` field**: scanner skips it. Pipelines without nodes are unusable anyway.

## Migration Plan

None. Zero migration is a core property of this change. Deployment = deploy new binary. The `projects/` root directory is created lazily by the first `PUT` to a project-scoped resource.

## Open Questions

None. All ten decisions locked after user sign-off on decisions 1 and 2.
