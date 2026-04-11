## Context

`PipelineResult` is a transient dataclass. The caller (`src/api/runs.py::trigger_run` and the pipeline gateway path) immediately throws it away after returning the HTTP 202. Nothing downstream can reach it. Change 1.6 wants to build an export business layer that reads a run's final_output by `run_id`; without persistence, that's impossible without re-running the whole pipeline.

The obvious question: **where does the data go?** Options considered:

### Option A — New columns on `workflow_runs`

Add `final_output: Text`, `outputs: JSONB`, `failed_node: String`, `paused_at: String` as first-class columns.

- **Pros:** strongly typed, indexable, queryable via SQL.
- **Cons:** requires a migration; ossifies the shape of `PipelineResult` in the schema; future additions (token counts, model versions, retry counts) each need a new column.
- **Verdict:** over-engineered for a feature whose sole current consumer is the export layer reading one field.

### Option B — Drop the payload into `WorkflowRun.metadata_` (JSONB)

Extend `finish_run` / `update_run_status` with `result_payload: dict | None = None`; when provided, merge it into `metadata_` in the same transaction as the status transition.

- **Pros:** zero schema migration, one DB write, reuses an existing JSONB column that's already part of the run row, shape is free to evolve without touching the DB.
- **Cons:** less queryable (JSONB gin index would help if we ever needed it, which we don't yet), not strongly typed.
- **Verdict:** matches the pragmatic "solve the real problem, don't design for hypothetical futures" rule.

**Chosen: B.** If a future consumer needs column-level queries, promote specific JSONB keys to real columns then — additive, non-breaking.

### Option C — A separate `workflow_run_outputs` table

One-row-per-run sidecar keyed on `run_id`.

- **Pros:** isolates the write path; large `final_output` blobs don't bloat the run row.
- **Cons:** two writes per terminal transition, a new table + migration, a join for every read. Solves a performance problem we don't have (final_output is typically a few KB).
- **Verdict:** reject — premature optimization.

## Decisions

### Decision 1: `result_payload` is a kwarg on the existing `finish_run` / `update_run_status`, not a new function

Adding `persist_run_result(run_id, payload)` as a separate call would mean two transactions and two round-trips per terminal transition, plus a race window where the run is `completed` but `final_output` is still absent. Bundling the payload into the same call closes that window and keeps the call sites on `pipeline.py` one-liners (they're already calling `finish_run` / `update_run_status`).

The kwarg is keyword-only to make the existing positional signature impossible to break accidentally.

### Decision 2: Merge semantics are "shallow patch into `metadata_`", not replace

`WorkflowRun.metadata_` may already contain unrelated keys (there aren't any today, but the column is `default=dict` precisely to leave room). Merging instead of replacing preserves that invariant. Reassigning to a fresh dict (`run.metadata_ = {**existing, **patch}`) is required because SQLAlchemy does not track in-place JSONB mutations — an in-place `dict.update` would silently drop the change at flush time.

### Decision 3: The payload shape is exactly the non-status fields of `PipelineResult`

`{final_output: str, outputs: dict[str, str], failed_node: str | None, error: str | None, paused_at: str | None}`. `run_id` and `status` are already columns on `WorkflowRun`; persisting them again in JSONB would duplicate state and invite drift.

### Decision 4: Redis sync is not extended

The Redis `workflow_run:{run_id}` hash is for fast lookups of run status/timestamps in hot paths (gateway resume detection, bus session routing). `final_output` is read only by the export layer on the cold path; putting it in Redis would bloat every fast-path lookup to read a payload nobody uses there. Keep `_sync_to_redis` fields unchanged.

### Decision 5: Call sites on pipeline.py — 6 sites, all assemble the same dict

Three in `execute_pipeline`: graph-exec-exception branch (line ~313), pause branch (~342), completed/failed branch (~372).
Three mirrors in `resume_pipeline`: exception (~492), re-pause (~506), completed/failed (~529/~532).

Each site already has locals for `node_outputs`, `error`, `final_output`, `paused_at` where applicable. We build a dict literal at the call site and pass it. No helper function — three lines in six places is clearer than one helper with five optional params.

## Risks / Trade-offs

- **JSONB growth**: if a pipeline produces a 10 MB `final_output`, every `get_run` touches that payload. Mitigation: `get_run` already returns the full row; callers that don't need `metadata_` just ignore it. If this becomes a problem we promote to option C (sidecar table) — not now.
- **Schema-less data**: typos in the payload dict won't be caught by any schema check. Mitigation: the 6 call sites are in one file, all build the same 5-key dict; a single test asserting the keys after a real pipeline run catches regressions.
- **Future export-layer assumptions**: Change 1.6 will assume `final_output` is always `str` and never `None`. We guarantee that here by always writing `""` on terminal sites where the pipeline didn't produce output (failed, paused, empty final state) — never `None`.
