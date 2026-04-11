## 1. Business layer

- [x] 1.1 Fill `src/export/exporter.py`:
  - `@dataclass(frozen=True) class ExportArtifact`: `filename: str`, `content: str`, `content_type: str`
  - Exception classes: `ExportError(Exception)`, `RunNotFoundError(ExportError)`, `RunNotFinishedError(ExportError)`, `NoFinalOutputError(ExportError)`
  - Private helper `_sanitize_filename_part(name: str) -> str`: replace non-[A-Za-z0-9_-] with `_`
  - `async def export_markdown(run_id: str) -> ExportArtifact`:
    - Fetch run via `src.engine.run.get_run(run_id)`; None → `RunNotFoundError`
    - If `run.status != "completed"` → `RunNotFinishedError` with message including current status
    - Read `final_output = (run.metadata_ or {}).get("final_output") or ""` — empty or missing → `NoFinalOutputError`
    - Derive filename: `{_sanitize_filename_part(run.pipeline or "run")}_{run.run_id[:8]}.md`
    - Return `ExportArtifact(filename=..., content=final_output, content_type="text/markdown; charset=utf-8")`
- [x] 1.2 Fill `src/export/__init__.py`:
  - Re-export `ExportArtifact`, `export_markdown`, `ExportError`, `RunNotFoundError`, `RunNotFinishedError`, `NoFinalOutputError`

## 2. REST endpoint

- [x] 2.1 Create `src/api/export.py`:
  - `router = APIRouter(dependencies=[Depends(require_api_key)])`
  - `GET /runs/{run_id}/export` handler:
    - `try: artifact = await export_markdown(run_id)`
    - `except RunNotFoundError: raise HTTPException(404, "run not found")`
    - `except RunNotFinishedError as e: raise HTTPException(409, str(e))`
    - `except NoFinalOutputError: raise HTTPException(404, "run completed but has no exportable output")`
    - Build `Content-Disposition` header with both ASCII fallback and `filename*=UTF-8''<percent-encoded>` forms (helper `_content_disposition(filename: str) -> str` inline)
    - Return `Response(content=artifact.content.encode("utf-8"), media_type=artifact.content_type, headers={"Content-Disposition": ...})`

## 3. Wiring

- [x] 3.1 Modify `src/main.py`:
  - `from src.api.export import router as export_router`
  - `api_router.include_router(export_router)` after the other routers
- [x] 3.2 Import-check + route enumeration via `python -c "import src.main; ..."`

## 4. Tests

- [x] 4.1 `scripts/test_export_business.py` (no PG — monkey-patches `get_run`):
  - `RunNotFoundError` when get_run returns None
  - `RunNotFinishedError` for each non-completed status (`running`, `paused`, `failed`, `cancelled`)
  - `NoFinalOutputError` when `metadata_` has no `final_output` key
  - `NoFinalOutputError` when `final_output == ""`
  - Happy path: returns `ExportArtifact` with expected filename / content / content_type
  - Filename sanitization: pipeline name `"blog/test 中文"` → `blog_test____` + `_<8chars>.md` (non-ASCII collapses to `_`)
  - `run.pipeline is None` → filename `run_<8chars>.md`
- [x] 4.2 `scripts/test_rest_export.py` (PG required):
  - Create a run via `create_run`, stamp `metadata_` with `{"final_output": "# hello"}` via `finish_run(..., result_payload=...)`
  - GET the export endpoint → 200, `Content-Type: text/markdown; charset=utf-8`, `Content-Disposition` present + includes the derived filename, body equals `# hello`
  - GET for a run that's still `running` (skip the finish_run step) → 409
  - GET for `run_id="nonexistent"` → 404
  - GET for a completed run whose metadata_ is empty (use raw SQL to create a legacy-style row) → 404 with the distinct detail
  - Missing API key → 401 (patch `api_keys=["k"]`)

## 5. Validate + progress

- [x] 5.1 `openspec validate add-export-rest --strict`
- [ ] 5.2 Update `.plan/progress.md` — Phase 6.4 step 3 of ~5
- [ ] 5.3 Await user sign-off, then `openspec archive add-export-rest`
