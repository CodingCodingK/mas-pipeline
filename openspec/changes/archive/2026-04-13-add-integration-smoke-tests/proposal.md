## Why

Phase 6 delivered REST, SSE, LangGraph interrupts, and a full compose stack, but the only end-to-end coverage is fragmented unit tests. We have no single gate that proves "docker compose up → create project → run a pipeline with human-in-the-loop → export" still works as a wired whole. Phase 7 is the finishing phase; before we write user-facing docs we need one script that catches wiring regressions (routing, SSE, interrupt resume, export) against the real compose stack.

## What Changes

- Add `scripts/test_e2e_smoke.py`: a single pytest-style script that drives the live compose stack end-to-end using an embedded fake LLM server, covering the happy path plus the approve / reject / edit interrupt branches of `blog_with_review`.
- Add `docker-compose.smoke.yaml`: a compose override that points the `api` container at the embedded fake LLM via `OPENAI_API_BASE=http://host.docker.internal:9999/v1`. Base `docker-compose.yaml` is untouched.
- Modify `config/settings.yaml`: change `openai.api_base` from a hardcoded URL to `${OPENAI_API_BASE:https://api.openai.com/v1}`. The loader already supports `${VAR:default}` syntax, so this is a one-line change that keeps normal operation identical and lets the smoke override flip the endpoint cleanly.
- Scope is explicitly narrow: **mode B only** (real compose + real HTTP). Existing unit tests under `scripts/test_*.py` stay untouched — this script is additive, not a replacement.
- **RAG paths (file upload, ingest job, knowledge retrieval) are intentionally out of scope** for this change. The current embedding provider is broken in the active deployment (the codex-for.me proxy has no `/embeddings` endpoint); that is being fixed in the Post-Phase 7 "Local Embedding" backlog. After local embedding lands, `scripts/test_e2e_smoke.py` must be extended to cover upload → ingest → SSE-to-done → RAG-enabled pipeline run. This TODO is recorded in `.plan/next_task.md`.

## Capabilities

### New Capabilities
- `integration-smoke-tests`: single end-to-end script that runs the compose stack and validates project → agent override → interrupt pipeline → SSE → export, using an embedded fake LLM so the test stays offline-safe and deterministic.

### Modified Capabilities
<!-- none — config/settings.yaml change is implementation detail, not a spec requirement change -->

## Impact

- **New files**: `scripts/test_e2e_smoke.py`, `docker-compose.smoke.yaml`, `scripts/smoke_settings_shadow.yaml` (the last is bind-mounted over the developer's real `config/settings.local.yaml` inside the api container so their real LLM proxy config can't leak into the smoke run; it cannot be named `*.local.*` because the repo's gitignore masks that pattern).
- **Modified files**: `config/settings.yaml` (one line: `api_base` → env-var templated)
- **No API changes**, no DB schema changes, no frontend changes.
- **Dependencies**: requires `host.docker.internal` DNS resolution from inside the `api` container — works natively on Windows and macOS Docker Desktop; on Linux the override adds `extra_hosts: ["host.docker.internal:host-gateway"]`.
- **Runtime cost**: script brings up the compose stack, runs ~1 minute, tears down; not wired into CI in this change (CI integration is deliberately out of scope — it belongs to a future hardening pass).
- **Risk**: the `settings.yaml` env-var substitution is the only production-path change. The default value preserves current behavior exactly, so non-smoke runs are unaffected.
