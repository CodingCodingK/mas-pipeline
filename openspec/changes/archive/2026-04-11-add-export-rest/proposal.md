## Why

Users finish a pipeline run and then need to do something with the result — download it, hand it to a publishing flow, attach it to a ticket. Today there's nowhere to get it from: `execute_pipeline` returns `PipelineResult.final_output` in-memory and the caller drops it. Change 1.5 `add-pipeline-result-persistence` closed the write side — `final_output` now lives in `WorkflowRun.metadata_`. This change closes the read side: a business layer that extracts it cleanly and a REST route that serves it as a downloadable artifact.

Also: `src/export/exporter.py` and `src/export/__init__.py` are both 0-byte stubs left over from the phase-6 scaffolding. They should either be filled in or deleted; filling them in matches the frontend plan (Phase 6.4 Web UI has an "Export" button on the run detail page).

## What Changes

- **`src/export/exporter.py`**: new business-layer module. Public API is a single function `export_markdown(run_id: str) -> ExportArtifact` where `ExportArtifact` is a small dataclass `(filename: str, content: str, content_type: str)`. Reads `WorkflowRun` by `run_id`, validates state, pulls `final_output` out of `metadata_`, derives a filename from the pipeline name + short run_id, returns the artifact.
- **`src/export/__init__.py`**: re-exports `export_markdown`, `ExportArtifact`, and the three exception classes.
- **Exception classes** in `src/export/exporter.py`:
  - `ExportError` — base class, inherits `Exception`
  - `RunNotFoundError(ExportError)` — `run_id` unknown
  - `RunNotFinishedError(ExportError)` — run exists but status is not `completed` (failed / paused / cancelled / running all fail here)
  - `NoFinalOutputError(ExportError)` — run is completed but `metadata_['final_output']` is missing or empty (shouldn't happen post-1.5, but we handle the legacy-data case)
- **`src/api/export.py`**: new REST router under `/api/runs/{run_id}/export`, behind `Depends(require_api_key)`. Single endpoint `GET /api/runs/{run_id}/export` that calls `export_markdown(run_id)` and returns a `Response` with `Content-Type: text/markdown; charset=utf-8` and `Content-Disposition: attachment; filename="<derived>.md"`. Maps exceptions to HTTP: `RunNotFoundError` → 404, `RunNotFinishedError` → 409, `NoFinalOutputError` → 404 with a distinct detail.
- **`src/main.py`**: import and mount `export_router` under `api_router`.
- **Capability specs (ADDED):**
  - `export-business` — defines the exporter API, state validation rules, filename derivation, and exception classes.
  - `export-rest-api` — defines the single GET endpoint, status codes, headers, and body format.

## Out of Scope

- **PDF / DOCX / HTML export.** Markdown only in P0. The Web UI's export button will hit `?format=md` (default) and future work can add new format values without changing the URL shape.
- **Batch export.** Per-run only. A future `/api/projects/{id}/export` zip endpoint is a separate change.
- **Inline preview.** The endpoint returns a download. The Web UI can render `final_output` inline by reading it out of the existing `GET /api/runs/{run_id}` response (Change 1.5 persists it to `metadata_`, which that endpoint already returns).
- **Re-exporting historical runs created before Change 1.5.** Those runs have empty `metadata_` and will return `NoFinalOutputError` → 404. Not a regression — they never had the data.
- **Authorization beyond API key.** Per-user ACL on runs is a Phase 6.5 concern.

## Impact

- **New specs:** `export-business`, `export-rest-api` (both ADDED)
- **Affected code:** `src/export/exporter.py` (from 0 bytes → full module), `src/export/__init__.py` (exports), `src/api/export.py` (new), `src/main.py` (one import + one `include_router` line)
- **Backward compatibility:** no existing API or data contract changes. Legacy runs without `metadata_['final_output']` get a clean 404 with a documented detail message.
- **Tests:** `scripts/test_export_business.py` (no PG — uses a fake WorkflowRun) and `scripts/test_rest_export.py` (PG required — create run, stamp metadata_ via update_run_status, hit endpoint).
- **Depends on:** Change 1.5 (`add-pipeline-result-persistence`) — the `final_output` read path is only meaningful once writes are in place.
