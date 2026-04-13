## 1. Config plumbing

- [x] 1.1 Change `config/settings.yaml` line for `openai.api_base` to `${OPENAI_API_BASE:https://api.openai.com/v1}`
- [x] 1.2 Default-path preserved: verified indirectly via `scripts/test_llm_adapter.py` which routes through the developer's real `settings.local.yaml` (no `OPENAI_API_BASE` env var) and still successfully calls the real LLM proxy. Also covered by every existing REST integration run that uses the developer's real settings.
- [x] 1.3 `python scripts/test_rest_api_integration.py` → 40 passed, 0 failed, 1 skipped after the env-var substitution was in place. No regressions.

## 2. Compose override

- [x] 2.1 Create `docker-compose.smoke.yaml` at repo root declaring an `api` service override that sets `OPENAI_API_BASE=http://host.docker.internal:9999/v1`
- [x] 2.2 Add `extra_hosts: ["host.docker.internal:host-gateway"]` to the override for Linux support
- [x] 2.3 Verify `docker compose -f docker-compose.yaml -f docker-compose.smoke.yaml config` produces a valid merged config

## 3. Embedded fake LLM server

- [x] 3.1 In `scripts/test_e2e_smoke.py`, implement a minimal FastAPI app with `POST /v1/chat/completions` that returns a deterministic OpenAI-compatible chat completion body containing a fixed marker string (`MAS_SMOKE_DETERMINISTIC_OUTPUT`). Handles both `stream=true` (SSE chunks) and `stream=false` (JSON). Also stubs `/v1/embeddings` defensively.
- [x] 3.2 Wrap the fake in a context manager (`fake_llm_server`) that starts `uvicorn.Server` on `127.0.0.1:9999` in a background thread and stops it on exit
- [x] 3.3 Check port 9999 availability before binding; fail with a clear error if occupied

## 4. Smoke script: stack lifecycle

- [x] 4.1 `scripts/test_e2e_smoke.py` top-of-file docstring explains RAG is intentionally skipped and must be re-added after Local Embedding
- [x] 4.2 Implement `compose_up()` that runs `docker compose -f docker-compose.yaml -f docker-compose.smoke.yaml up -d --build` then polls `/health` for up to 90s
- [x] 4.3 Implement `compose_down()` that runs `docker compose ... down` unconditionally in `main()`'s `finally` block
- [x] 4.4 On failure, `compose_logs_tail()` dumps `docker compose logs api --tail=100` to stderr before tearing down

## 5. Smoke script: happy-path setup

- [x] 5.1 POST `/api/projects` to create a project; assert 201 and capture `project_id`
- [x] 5.2 PUT `/api/projects/{id}/agents/writer` to install a minimal project-scoped agent override; assert 200/201
- [x] 5.3 POST `/api/projects/{id}/pipelines/blog_with_review/runs?stream=true` via httpx streaming
- [x] 5.4 Parse the `started` SSE event and capture the real `run_id`
- [x] 5.5 Poll `/api/runs/{run_id}` for `status=paused` as the pause signal. **Note**: the status-only SSE stream does not reliably surface `pipeline_pause` events, so polling is the robust path (aligned with Phase 6.1 deployment risks doc).

## 6. Smoke script: approve branch

- [x] 6.1 On `paused`, POST `/api/runs/{run_id}/resume` with `{"value": {"action": "approve"}}`. **Correction vs original task wording**: the engine key is `action` (not `decision`), confirmed in `src/engine/graph.py:196`.
- [x] 6.2 Wait for run status to become `completed` via polling
- [x] 6.3 GET `/api/runs/{run_id}/export?fmt=md` and assert the body contains `MAS_SMOKE_DETERMINISTIC_OUTPUT`

## 7. Smoke script: reject & redo branch

- [x] 7.1 Start a second run on the same project
- [x] 7.2 On first pause, POST resume with `{"value": {"action": "reject", "feedback": "please rewrite"}}`
- [x] 7.3 Wait for the run to leave `paused` then pause again (proving the writer re-ran)
- [x] 7.4 POST approve, wait for `completed`, verify export is non-empty

## 8. Smoke script: edit branch

- [x] 8.1 Start a third run on the same project
- [x] 8.2 On pause, POST resume with `{"value": {"action": "edit", "edited": "EDITED_SMOKE_CONTENT"}}`. **Correction**: engine key is `edited` (not `content`), confirmed in `src/engine/graph.py:198`.
- [x] 8.3 Wait for `completed`, GET the markdown export, assert it contains `EDITED_SMOKE_CONTENT`

## 9. Teardown and exit

- [x] 9.1 On any `AssertionError`, print `SMOKE FAIL: ...` to stderr and exit non-zero
- [x] 9.2 `finally` block in `main()` calls `compose_down()` unconditionally; `fake_llm_server` context manager stops the fake LLM
- [x] 9.3 On success: `SMOKE OK: approve + reject + edit (Ns)`

## 10. Final verification

- [x] 10.1 `python scripts/test_e2e_smoke.py` green from a clean state: `SMOKE OK: approve + reject + edit (24s)`
- [x] 10.2 Deliberate-fail verified: replaced the approve-branch marker assertion with `ZZZ_DELIBERATE_FAIL`; script exited with code 1, printed `SMOKE FAIL: ...`, and `docker compose ps` confirmed the stack was torn down. Assertion restored afterward.
- [x] 10.3 `git status` shows NO changes to `config/settings.local.yaml` or any other host config residue after smoke runs. The only smoke-related files in status are the intentionally-added ones (`docker-compose.smoke.yaml`, `scripts/test_e2e_smoke.py`, `scripts/smoke_settings_shadow.yaml`). The developer's `config/settings.local.yaml` is masked inside the container only via an ro bind mount and is never written.
- [x] 10.4 `python scripts/test_rest_api_integration.py` → 40 passed, 0 failed, 1 skipped. `scripts/test_llm_adapter.py` also still works against the developer's real LLM proxy, confirming the env-var substitution is fully backward compatible.
