## Context

Change 1.5 just landed write-side persistence: `finish_run(..., result_payload={...})` merges `final_output`, `outputs`, `error` into `WorkflowRun.metadata_`. The read side needs to be a *narrow* counterpart — single format, single endpoint, single code path — because the whole point of splitting 1.5 and 1.6 was to keep each change small and reviewable.

The big design question: **what does the business layer look like?** Specifically, how thin or thick a layer sits between the HTTP handler and the DB row. Options:

### Option A — Thin adapter: REST handler reads `WorkflowRun` directly

The handler fetches the run, inspects status, pulls `metadata_['final_output']`, builds the response.

- **Pros:** one file, no indirection.
- **Cons:** business rules (state validation, filename derivation, error taxonomy) end up inside a FastAPI handler where they can't be unit-tested without a `TestClient`. The frontend will need the same "is this run exportable?" check for its Export button's enabled state — duplicating that logic across handler and UI is a smell.
- **Verdict:** reject. Even for one format, the rules belong in a pure function that can be tested and called from multiple surfaces.

### Option B — Business layer with dataclass return

A function `export_markdown(run_id) -> ExportArtifact` that owns validation and filename derivation. The REST handler is a 10-line adapter: call it, map exceptions to status codes, wrap in a `Response`.

- **Pros:** unit-testable without HTTP, reusable from a future `/projects/{id}/export` batch endpoint, clean error taxonomy via exception classes.
- **Cons:** two files instead of one.
- **Verdict:** chosen.

### Option C — Full abstraction: pluggable exporter registry

A registry keyed on format, `register_exporter("md", markdown_exporter)`, with a dispatch function.

- **Pros:** adding PDF is one file.
- **Cons:** we don't have PDF today and might never. Registry adds indirection that pays off at three formats, not one.
- **Verdict:** reject. When PDF lands, promote Option B to Option C at that time — additive, non-breaking.

**Chosen: B.**

## Decisions

### Decision 1: Business layer lives in `src/export/exporter.py`, filled into the existing 0-byte stub

The directory already exists from the phase-6 scaffolding. Reusing it matches the pattern of `src/api/files.py` in Change 1 (also filled into a 0-byte stub) and keeps the dir tree stable — no one has to update a `src/export/` → `src/exports/` import somewhere.

### Decision 2: `ExportArtifact` is a dataclass, not a Pydantic model

Pydantic would force a validation pass on a field the exporter just *computed* from trusted internal state — pointless work. A `@dataclass(frozen=True)` is simpler and keeps the business module free of FastAPI dependencies, so it can be called from the bus gateway or a future scheduled job.

```python
@dataclass(frozen=True)
class ExportArtifact:
    filename: str
    content: str
    content_type: str  # e.g. "text/markdown; charset=utf-8"
```

### Decision 3: Exception taxonomy — three classes, all inheriting `ExportError`

The handler has to map to three distinct HTTP responses:

| Exception               | HTTP | Why                                                      |
|-------------------------|------|----------------------------------------------------------|
| `RunNotFoundError`      | 404  | `run_id` does not exist                                  |
| `RunNotFinishedError`   | 409  | Run exists but status ≠ `completed` (can't export yet)   |
| `NoFinalOutputError`    | 404  | Run is completed but metadata_ is missing the field      |

`NoFinalOutputError` is technically "data exists but not what we need" — could be 404 or 422. 404 with a distinct detail (`"run completed but has no exportable output"`) matches what frontends will want to display, and keeps the endpoint's error surface uniform (404 for "nothing to download" of either flavor, 409 for "not ready yet").

Sharing a base class `ExportError` lets future callers (e.g. a CLI) catch everything with one except. Not strictly needed now but costs one line.

### Decision 4: Only `completed` status is exportable — not `failed` or `paused`

`failed` runs have `final_output == ""` by Change 1.5's invariant — exporting would hand the user a zero-byte markdown file, which is worse than a clear error. `paused` runs may have partial outputs but aren't done. `cancelled` is ambiguous. Restricting to `completed` keeps the contract simple: the export endpoint returns *the* final output, not *a* partial.

If a future use case wants partial export, add a `?allow_partial=1` query param — additive.

### Decision 5: Filename derivation is `{pipeline}_{run_id_short}.md`

Where `pipeline` is `WorkflowRun.pipeline` (falling back to `"run"` if null — which happens for runs created without a pipeline, though none exist in practice), and `run_id_short` is the first 8 chars of `run_id` (which is a 16-char hex uuid). Slashes, spaces, and other filename-unfriendly characters in the pipeline name are replaced with `_` via a small normalizer; we don't touch the original pipeline name elsewhere.

**Example:** `blog_generation_a1b2c3d4.md`.

Not `{filename}_{timestamp}.md` because the timestamp would add a column-join to `started_at` and the run_id prefix is already unique.

### Decision 6: Endpoint returns `Response`, not `FileResponse`

`FileResponse` streams from disk — we have the content in memory (it's a string that's already in `metadata_`). `Response(content=artifact.content, media_type=..., headers={...})` is the right primitive. A stray `.encode()` call takes care of string → bytes.

### Decision 7: `Content-Disposition` filename is quoted + ASCII-escaped

If the pipeline name contains non-ASCII (e.g. Chinese pipeline names, which are common in this project), the raw `filename=...` parameter is ambiguous per RFC 6266. Use the `filename*=UTF-8''<percent-encoded>` form *in addition to* the ASCII fallback, so both legacy and modern browsers get it right. FastAPI's handler code builds that header manually (two lines).

## Risks / Trade-offs

- **Stale-data window:** if `WorkflowRun` status transitions to `completed` but `metadata_` writes haven't flushed (shouldn't happen post-1.5 — status and payload go in the same transaction — but defensive code is defensive), the exporter sees `completed` + empty final_output and raises `NoFinalOutputError`. That's the right behavior: the user gets 404 "no exportable output", not a zero-byte download.
- **Content size:** a 10 MB `final_output` means a 10 MB allocation on every export hit. Mitigation: if this ever matters, promote to a sidecar `workflow_run_outputs` table with streaming reads — deferred, YAGNI.
- **Pipeline rename:** `WorkflowRun.pipeline` is set at creation time and stable; renames on disk don't change historical run filenames. That's the right behavior (exports are a historical artifact, not a "current state" view).
- **Frontend coupling:** the Web UI will read `metadata_['final_output']` directly from `GET /api/runs/{run_id}` for inline preview, *not* go through the export endpoint. The export endpoint is exclusively for the "Download" action. No hidden coupling between the two reads.
