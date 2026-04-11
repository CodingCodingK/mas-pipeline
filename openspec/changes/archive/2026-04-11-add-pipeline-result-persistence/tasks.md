## 1. Run lifecycle API

- [x] 1.1 Modify `src/engine/run.py::update_run_status`:
  - Add keyword-only parameter `result_payload: dict | None = None`
  - Inside the existing `async with get_db() as session` block, if `result_payload is not None`, compute `merged = {**(run.metadata_ or {}), **result_payload}` and assign `run.metadata_ = merged` (reassignment, not in-place update, so SQLAlchemy flushes the JSONB column)
  - Preserve all existing behavior: transition validation, Redis sync, return value
- [x] 1.2 Modify `src/engine/run.py::finish_run`:
  - Same `result_payload: dict | None = None` kwarg
  - Same merge-and-reassign logic inside the existing session block
  - `session.flush()` + `session.refresh(run)` already present — no new round-trip
- [x] 1.3 No changes to `_sync_to_redis` (Decision 4)

## 2. Pipeline call sites

- [x] 2.1 `src/engine/pipeline.py::execute_pipeline` — graph-exec-exception branch (~line 313):
  - Pass `result_payload={"final_output": "", "outputs": {}, "failed_node": None, "error": str(exc), "paused_at": None}` to `finish_run(run_id, RunStatus.FAILED, result_payload=...)`
- [x] 2.2 `execute_pipeline` — pause branch (~line 342):
  - Pass `result_payload={"final_output": "", "outputs": final_state.get("outputs", {}), "failed_node": None, "error": None, "paused_at": paused_at}` to `update_run_status(run_id, RunStatus.PAUSED, result_payload=...)`
- [x] 2.3 `execute_pipeline` — completed/failed branch (~line 367-372):
  - Build `payload = {"final_output": final_output, "outputs": node_outputs, "failed_node": None, "error": error, "paused_at": None}`
  - Pass it to the appropriate `finish_run` call (both COMPLETED and FAILED arms)
- [x] 2.4 `resume_pipeline` — exception branch (~line 492): mirror 2.1
- [x] 2.5 `resume_pipeline` — re-pause branch (~line 506): mirror 2.2
- [x] 2.6 `resume_pipeline` — completed/failed branch (~line 527-532): mirror 2.3

## 3. Spec updates

- [x] 3.1 Add MODIFIED requirements + scenarios to `specs/pipeline-run/spec.md`:
  - `update_run_status` accepts optional `result_payload` and merges into `metadata_`
  - `finish_run` accepts optional `result_payload` and merges into `metadata_`
  - Merge semantics: shallow patch, reassignment (not in-place), unrelated keys preserved
  - None passthrough: `result_payload=None` changes `metadata_` exactly zero bytes

## 4. Tests

- [x] 4.1 Create `scripts/test_pipeline_result_persistence.py` (PG required):
  - Section 1 — run.py API:
    - `update_run_status` with `result_payload={"final_output": "hi"}` → read back, metadata_['final_output'] == "hi"
    - Second `update_run_status` with `result_payload={"error": "boom"}` → metadata_ has both keys (merge preserved)
    - Third `update_run_status` with `result_payload=None` → metadata_ unchanged
    - `finish_run` with `result_payload={"final_output": "done"}` → metadata_ has it, status=completed, finished_at set
    - Unrelated pre-existing metadata_ key (set via raw SQL) survives the merge
  - Section 2 — integration:
    - Create a `WorkflowRun`, drive it through `create_run → update_run_status(RUNNING) → finish_run(COMPLETED, result_payload=full_payload)` — assert `metadata_` has all 5 expected keys
- [x] 4.2 Regression: run full Phase 6.1/6.2/6.3 test suite — zero regressions (existing callers pass no kwarg and behave unchanged)

## 5. Validate and archive

- [x] 5.1 `openspec validate add-pipeline-result-persistence --strict`
- [x] 5.2 Update `.plan/progress.md` (Phase 6.4 step 2 of ~5)
- [ ] 5.3 Await user sign-off, then `openspec archive add-pipeline-result-persistence`
