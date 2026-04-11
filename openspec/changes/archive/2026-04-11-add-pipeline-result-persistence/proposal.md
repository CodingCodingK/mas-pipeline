## Why

`execute_pipeline` / `resume_pipeline` build a `PipelineResult` dataclass (`run_id`, `status`, `outputs`, `final_output`, `failed_node`, `error`, `paused_at`) and return it to the caller — but **nothing writes those fields to persistent storage**. Once the coroutine returns, `final_output` and the full node-output map are gone. `WorkflowRun` only records `status` / `started_at` / `finished_at`.

This is a blocker for the export layer (Change 1.6 `add-export-rest`): a user who POSTs `/runs/{run_id}/export` has no way to retrieve the pipeline's final content — it was never persisted. Telemetry records *that* a pipeline finished, not *what* it produced.

It's also a silent functional regression: pipelines run to completion and the caller drops their output on the floor the moment execution returns.

## What Changes

- **`engine/run.py`**: extend `finish_run` and `update_run_status` with an optional keyword-only `result_payload: dict | None = None` parameter. When provided, merge the patch into `WorkflowRun.metadata_` (reassigned as a fresh dict so SQLAlchemy flushes the JSONB column) in the same session as the status transition — one DB write, not two.
- **`engine/pipeline.py`**: at every terminal return site in `execute_pipeline` and `resume_pipeline` (completed, failed, paused — 6 sites total), build a dict `{final_output, outputs, failed_node, error, paused_at}` and pass it as `result_payload` to the existing `finish_run` / `update_run_status` call. No new call sites.
- **`pipeline-run` capability spec**: MODIFIED to add persistence requirements and scenarios documenting the `result_payload` merge semantics.

**Explicitly out of scope:** exporters, REST export routes, new DB columns, schema migrations. We write into the existing `metadata_` JSONB column — zero migration, zero schema churn.

## Impact

- **Affected specs:** `pipeline-run` (MODIFIED — `update_run_status`, `finish_run`, Redis sync requirements gain scenarios covering `result_payload`)
- **Affected code:** `src/engine/run.py` (2 signatures), `src/engine/pipeline.py` (6 call sites in `execute_pipeline` + `resume_pipeline`)
- **Backward compatibility:** preserved. `result_payload` defaults to `None`; existing callers (tests, cancel flow in `src/api/runs.py`) pass nothing and behave identically. Empty-metadata runs stay empty.
- **New tests:** `scripts/test_pipeline_result_persistence.py` — unit-level coverage of the `run.py` API (patch merge, None no-op, status transition still atomic) + one integration check that drives a tiny pipeline end-to-end and reads `metadata_['final_output']` back from PG.
- **Unblocks:** Change 1.6 `add-export-rest`, whose business layer will read `run.metadata_['final_output']`.
