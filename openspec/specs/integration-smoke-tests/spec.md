# Integration Smoke Tests

## Purpose

One end-to-end gate that runs the live docker-compose stack and validates
the complete REST → engine → SSE → interrupt → export flow against real
HTTP, using an embedded deterministic fake LLM so the test stays offline-safe
and reproducible. Additive to — not a replacement for — the existing unit
test suite under `scripts/test_*.py`.

## Requirements

### Requirement: End-to-end smoke script drives the live compose stack

The system SHALL provide `scripts/test_e2e_smoke.py`, a single executable script that brings up the compose stack, drives the full project → pipeline → export flow via real HTTP, and tears the stack down. The script SHALL fail with a non-zero exit code on any assertion failure, HTTP error, or missing event.

#### Scenario: Script runs green against a clean environment
- **WHEN** a developer runs `python scripts/test_e2e_smoke.py` on a machine with Docker Desktop running
- **THEN** the script starts the compose stack with the smoke override, waits for `/health` to return 200, runs all assertions, tears the stack down, and exits with status 0

#### Scenario: Script fails loudly on wiring regression
- **WHEN** any HTTP request returns a non-2xx status, any expected SSE event is missing, or any exported artifact is empty
- **THEN** the script prints the failing step and exits with a non-zero status

### Requirement: Smoke script covers the happy path

The script SHALL exercise the full REST surface required for a minimal end-to-end run: create project, create a project-scoped agent override, trigger a pipeline run via SSE, capture the real `run_id`, and fetch the markdown export.

#### Scenario: Happy-path blog run to export
- **WHEN** the script creates a project, PUTs agent overrides, POSTs to `/projects/{id}/pipelines/blog_with_review/runs?stream=true`, and reads the `started` SSE event
- **THEN** it captures the real `run_id`, subsequently polls the run to `completed`, and a GET to `/runs/{run_id}/export?fmt=md` returns a non-empty markdown body containing the deterministic fake-LLM marker

### Requirement: Smoke script covers all three interrupt branches

The script SHALL exercise the human-in-the-loop interrupt paths of `blog_with_review`: **approve**, **reject & redo**, and **edit**. Each branch SHALL be driven by posting to `/runs/{run_id}/resume` with the appropriate payload and verified by observing the run reach a terminal state. The resume payload uses the engine's real key names `action` and `edited` (not `decision`/`content`).

#### Scenario: Approve branch
- **WHEN** a run pauses at the review interrupt and the script POSTs `{"value": {"action": "approve"}}` to `/runs/{run_id}/resume`
- **THEN** the run transitions from `paused` to `completed` and the export contains the deterministic fake-LLM content

#### Scenario: Reject & redo branch
- **WHEN** a run pauses at the review interrupt and the script POSTs `{"value": {"action": "reject", "feedback": "..."}}` to `/runs/{run_id}/resume`
- **THEN** the run re-enters the writer node, produces a new draft, pauses again, and can be completed with a subsequent approve

#### Scenario: Edit branch
- **WHEN** a run pauses at the review interrupt and the script POSTs `{"value": {"action": "edit", "edited": "..."}}` to `/runs/{run_id}/resume`
- **THEN** the run transitions to `completed` and an `include_all=true` markdown export contains the user-provided edited content verbatim in the writer's output slot

### Requirement: Smoke script uses an embedded deterministic fake LLM

The script SHALL start an embedded HTTP server bound to `0.0.0.0:9999` implementing a minimal `POST /v1/chat/completions` endpoint that returns deterministic canned responses (both streaming and non-streaming forms). The compose stack SHALL be configured via `docker-compose.smoke.yaml` to point `OPENAI_API_BASE` at `http://host.docker.internal:9999/v1` so the `api` container routes all LLM calls to the fake. The script SHALL NOT make outbound requests to any real LLM provider. The fake MUST bind `0.0.0.0` (not `127.0.0.1`) so `host.docker.internal` from inside the `api` container can reach it.

#### Scenario: Fake LLM lifecycle is tied to the script
- **WHEN** the script starts
- **THEN** it binds the fake LLM server on port 9999 before starting the compose stack, and tears the server down in its `finally` block after the stack is down, even on assertion failure

#### Scenario: Fake LLM returns deterministic content
- **WHEN** the `api` container POSTs to `http://host.docker.internal:9999/v1/chat/completions`
- **THEN** the fake returns an OpenAI-compatible chat completion response (streaming chunks when `stream=true`, JSON otherwise) with a fixed deterministic body, so every smoke run produces identical pipeline outputs

### Requirement: Settings support an env-var-driven LLM base URL

`config/settings.yaml` SHALL set `openai.api_base` using the `${OPENAI_API_BASE:https://api.openai.com/v1}` substitution form supported by the config loader. When `OPENAI_API_BASE` is not set, behavior MUST be identical to the previous hardcoded value. Because `config/settings.local.yaml` deep-merges over `settings.yaml` and in practice contains a developer's real LLM proxy URL, the smoke compose override MUST additionally shadow `/app/config/settings.local.yaml` inside the api container with a read-only bind mount of `scripts/smoke_settings_shadow.yaml` so the local file cannot leak into smoke runs.

#### Scenario: Default operation is unchanged
- **WHEN** the stack starts without `OPENAI_API_BASE` in the environment and without any compose override
- **THEN** the effective `openai.api_base` resolves to `https://api.openai.com/v1` (or whatever the developer's `settings.local.yaml` specifies), identical to pre-change behavior

#### Scenario: Smoke override redirects LLM traffic
- **WHEN** the stack starts with `docker-compose.smoke.yaml` layered on top, `OPENAI_API_BASE=http://host.docker.internal:9999/v1`, and `scripts/smoke_settings_shadow.yaml` bind-mounted over `settings.local.yaml`
- **THEN** the `api` container's resolved LLM base URL points at the fake server and no outbound calls reach real providers, regardless of what the developer's host-side `settings.local.yaml` contains

### Requirement: Existing unit tests remain untouched

This change SHALL NOT modify, delete, or replace any existing test under `scripts/test_*.py`. The smoke script is additive; the existing unit-level coverage remains the authoritative gate for per-module behavior.

#### Scenario: No existing test files are edited
- **WHEN** the change is applied
- **THEN** `git diff --name-only` shows no modifications under `scripts/test_*.py` other than the newly-added `scripts/test_e2e_smoke.py`

### Requirement: RAG paths are explicitly out of scope

The smoke script SHALL NOT exercise file upload, ingest jobs, knowledge retrieval, or any pipeline that performs RAG. A comment at the top of `scripts/test_e2e_smoke.py` SHALL explain that RAG coverage is deferred until the Post-Phase 7 Local Embedding backlog is completed, and that the script must be extended at that point.

#### Scenario: Script does not call RAG endpoints
- **WHEN** a developer greps the script for `/files`, `/ingest`, `/knowledge`, or `/chunks`
- **THEN** no matches are found
