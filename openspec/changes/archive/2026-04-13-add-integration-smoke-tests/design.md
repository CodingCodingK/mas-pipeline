## Context

The compose stack from `add-docker-compose-full-stack` (archived 2026-04-12) is live on localhost and healthy. The backend has 101 unit tests covering REST, engine, storage, and agent factory layers, but nothing wires them together against the real Docker stack. Phase 6 also landed the LangGraph interrupt flow (`blog_with_review` pipeline with approve / reject / edit branches) and the `paused_output` pause-state fix — neither is covered by an end-to-end assertion.

The embedding/RAG path is currently broken on the deployed stack because `codex-for.me` (our chat LLM proxy) has no `/embeddings` endpoint. That is being fixed in the Post-Phase 7 Local Embedding backlog, not in this change.

We need one script that proves the stack can complete a full human-in-the-loop pipeline run end-to-end. It must be offline-safe (no real LLM calls), deterministic (same inputs → same outputs), and crash-safe (no config residue on the host even if the script dies mid-run).

## Goals / Non-Goals

**Goals:**
- Single script (`scripts/test_e2e_smoke.py`) that is the "is the wiring correct" gate.
- Exercises all three `blog_with_review` interrupt branches (approve, reject & redo, edit).
- Runs against the real compose stack — no in-process FastAPI TestClient shortcut.
- Deterministic and offline: uses an embedded fake LLM server; no real API keys required.
- Crash-safe: if the script dies, the host config is unchanged and no stray files remain.
- One-line, backward-compatible change to `config/settings.yaml`.

**Non-Goals:**
- **Mode A (in-process)** — explicitly dropped. The existing unit tests already cover in-process wiring; a second mode would double the maintenance cost for marginal value.
- **RAG coverage** (files / ingest / knowledge) — deferred until Local Embedding lands. TODO recorded in `.plan/next_task.md`.
- **CI integration** — this script is for local pre-release gating; wiring it into CI belongs to a future production-hardening pass.
- **Load / performance testing** — functional wiring only.
- **Replacing existing unit tests** — this is additive.

## Decisions

### Decision 1: LLM mocking via compose override + env-var templating (Method Q)

**Choice**: Add `docker-compose.smoke.yaml` that sets `OPENAI_API_BASE=http://host.docker.internal:9999/v1` on the `api` service, and change `config/settings.yaml`'s `openai.api_base` line to `${OPENAI_API_BASE:https://api.openai.com/v1}`. The smoke script starts an embedded FastAPI fake LLM on port 9999 before `docker compose up`.

**Alternatives considered**:
- **Method P (`settings.local.yaml` file override)**: works, but leaves on-disk residue if the script crashes between setup and teardown. A stale `settings.local.yaml` would silently poison the developer's next real run.
- **Inject an API key for a "fake provider" codepath in source**: would require adding test-only branches to production code. Rejected on principle.
- **Mount a tmpfs over `/app/config/settings.yaml` inside the container**: more moving parts than a compose override for no extra benefit.

**Why Q wins**: compose overrides compose on `up` and cleanly disappear on `down`. The host filesystem is never touched. The `settings.yaml` change is one line and uses the `${VAR:default}` syntax that `src/project/config.py` already supports — default behavior is byte-identical to the current build.

**Implementation wrinkle discovered during apply**: `config/settings.local.yaml` deep-merges over `settings.yaml`, and developers in practice pin `openai.api_base` to their real LLM proxy there. The env-var substitution on `settings.yaml` alone is therefore not sufficient — the local file wins. Fix: `docker-compose.smoke.yaml` also bind-mounts `scripts/smoke_settings_shadow.yaml` read-only over `/app/config/settings.local.yaml` inside the api container. This shadows the developer's local file for the smoke run only; the host file is never touched. The shadow file cannot be named `*.local.*` because the repo's gitignore masks that pattern (would prevent committing it).

### Decision 2: Embedded fake LLM in the script itself, not a container

**Choice**: The fake LLM is a small FastAPI app started via `uvicorn.Server` in a background thread inside `scripts/test_e2e_smoke.py`. It binds `127.0.0.1:9999` on the host. The `api` container reaches it via `host.docker.internal:9999`.

**Alternatives considered**:
- **Fake LLM as a fourth compose service**: would require a separate Dockerfile, image build, volume for the canned responses, and wiring into the compose network. More surface area, no benefit.
- **Static HTTP mock via `mockoon` / `wiremock`**: another tool to install; we already have FastAPI.

**Why**: the script owns the fake's lifecycle — start fake, start stack, drive assertions, stop stack, stop fake — in one `try/finally`. The fake dies with the script, no orphans possible.

### Decision 3: Canned responses per-endpoint, not per-turn

**Choice**: The fake returns one fixed JSON body for every `/v1/chat/completions` call, regardless of the input prompt. The blog pipeline's three agents (writer, reviewer, editor) all see the same deterministic completion text. Assertions check for the presence of this known string in the exported markdown.

**Alternatives considered**:
- **Route responses by system-prompt sniffing**: fragile (the prompt template can drift without breaking tests that match it).
- **Record-and-replay real responses**: ties tests to a real provider snapshot; breaks reproducibility when models change.

**Why**: the smoke test is a wiring gate, not a content-quality gate. Deterministic-and-boring is the right trade.

### Decision 4: `host.docker.internal` with a Linux fallback

**Choice**: On Windows and macOS Docker Desktop, `host.docker.internal` resolves out of the box. On Linux, the compose override adds `extra_hosts: ["host.docker.internal:host-gateway"]` to the `api` service.

**Risk**: rootless / Podman setups may not support `host-gateway`. The script will document this as a known limitation — the primary dev environment is Windows Docker Desktop, which works.

### Decision 5: Blog pipeline is the only covered pipeline

**Choice**: Only `blog_with_review` is driven by the smoke script. The other seeded pipelines (e.g., `courseware_*`) share the same REST and engine code paths, so exercising the second pipeline adds little signal for a lot of runtime.

## Risks / Trade-offs

- **Risk**: `host.docker.internal` doesn't resolve on some Linux distros → Mitigation: the override declares `extra_hosts: host-gateway`; a one-line README note covers the remaining edge case.
- **Risk**: The embedded fake server port (9999) may be in use → Mitigation: script checks the port before binding and fails with a clear error message instead of silently racing.
- **Risk**: Compose stack takes ~30s to become healthy on a cold start; script may time out → Mitigation: poll `/health` with a 60s budget and print the `docker compose logs api` tail on failure so the cause is immediately visible.
- **Risk**: The `${VAR:default}` substitution in `settings.yaml` behaves differently than the current hardcoded value → Mitigation: one unit-style check in the script asserts the resolved URL equals the fake when the override is active; the default path is unchanged by construction.
- **Risk**: Script leaves the compose stack running on assertion failure → Mitigation: `try/finally` around the whole flow runs `docker compose -f docker-compose.yaml -f docker-compose.smoke.yaml down` unconditionally.
- **Trade-off**: No RAG coverage means ingest-path regressions can slip through → Accepted and logged in `.plan/next_task.md`; will be fixed when Local Embedding lands.
- **Trade-off**: Not in CI yet → Accepted; Phase 7 is about finishing, not about building CI infrastructure.

## Migration Plan

1. Land the `settings.yaml` one-line change first. Verify a normal `docker compose up` still works and the resolved `openai.api_base` is unchanged.
2. Add `docker-compose.smoke.yaml` and `scripts/test_e2e_smoke.py` together.
3. Run the script locally; archive the change only after it goes green against the real stack.

**Rollback**: revert all three files. The `settings.yaml` change is the only one that touches the production path, and reverting restores the hardcoded URL verbatim.

## Open Questions

- None blocking. The decisions above are final pending review.
