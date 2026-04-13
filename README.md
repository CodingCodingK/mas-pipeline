# mas-pipeline

A configurable Multi-Agent System engine for content production pipelines.

Define agent roles in Markdown, wire them into pipelines with YAML — zero code to add a new workflow.

## Features

- **Agent Loop (ReAct)** — autonomous LLM agents with tool calling
- **Pipeline Engine** — YAML-configured multi-agent workflows
- **Multi-Provider LLM** — Anthropic / OpenAI / Gemini / DeepSeek / Ollama
- **RAG** — multimodal document parsing + pgvector retrieval
- **Memory** — cross-session persistent knowledge
- **Task System** — DAG-based multi-agent coordination
- **LangGraph Integration** — checkpoint + human-in-the-loop for critical workflows
- **Sandbox** — kernel-level confinement of ShellTool via bubblewrap (Linux) / sandbox-exec (macOS)
- **Telemetry** — token usage, latency, tool call tracking with web dashboard

## Sandbox

ShellTool commands are wrapped in a kernel-level sandbox so that path and network confinement does not depend on string-pattern Permission rules.

| Platform | Backend | How to install |
|---|---|---|
| Linux / WSL2 | `bubblewrap` (`bwrap`) | `apt install bubblewrap` (or `dnf install bubblewrap`) |
| macOS | `sandbox-exec` | built in (`/usr/bin/sandbox-exec`) |
| Windows | — | passthrough with one-time warning at startup |

Configuration in `config/settings.yaml`:

```yaml
sandbox:
  enabled: true              # default — wrap when supported
  fail_if_unavailable: false # set true to refuse boot when bwrap is missing
```

The sandbox derives its writable / readable path lists from your active Permission rules: `Edit("projects/**")` becomes `--bind projects projects` automatically. Network is fully unshared inside the sandbox; tools that need network (WebSearch, MCP) run in the parent Python process and bypass it.

## RAG / Embedding

RAG is an optional feature. The server starts and every non-RAG feature (chat, pipelines, export) works regardless of whether an embedding service is available. The agent `search_docs` tool degrades to a "no results" response when embedding is unreachable; REST ingest jobs surface a structured error payload.

Three ways to run it:

**A. Local ollama (shipped default, zero config)**
```bash
ollama pull nomic-embed-text
# settings.yaml default: api_base=http://localhost:11434/v1, dimensions=768
```

**B. External OpenAI-compatible API** — add to `config/settings.local.yaml`:
```yaml
embedding:
  model: text-embedding-3-small
  dimensions: 1536
  api_base: https://api.openai.com/v1
  api_key: sk-...
```
Then run `python scripts/migrate_embedding_dim.py --yes` to reshape `document_chunks.embedding` to match, and re-ingest affected files.

**C. No RAG** — leave defaults, don't run ollama. The project still runs; RAG endpoints return a structured 503-equivalent Job error.

Embedding config is **independent** of the chat provider block — setting `providers.openai.api_base` to a chat-only proxy does not affect the embedder.

## Monitoring (optional)

`mas-pipeline` exposes a Prometheus-format `/metrics` endpoint covering 5 operational signals:

| Metric | Type | Meaning |
|---|---|---|
| `sessions_active` | gauge | SessionRunner instances currently alive |
| `workers_running` | gauge | In-flight jobs + in-flight sub-agent workers |
| `pg_connections_used` | gauge | SQLAlchemy pool connections checked out |
| `sse_connections` | gauge | Open SSE long-poll connections |
| `messages_total` | counter | Cumulative event-bus emits |

A bundled Prometheus + Grafana stack is shipped as an **opt-in compose profile** — default `docker compose up` does NOT start it.

```bash
# Opt in:
docker compose --profile monitoring up
```

Then open:

- Grafana at `http://localhost:3000` (login `admin` / `admin`)
- The pre-provisioned `mas-pipeline` dashboard appears automatically under Dashboards

Ports: `PROMETHEUS_PORT=9090` / `GRAFANA_PORT=3000` (both configurable via `.env`).

The metrics endpoint is always live (even without the monitoring profile) — hit `http://localhost/metrics` directly with `curl` to see the raw text format.

> **Single-worker constraint**: `mas-pipeline` runs as a single uvicorn worker. Setting `WEB_CONCURRENCY>1` or `UVICORN_WORKERS>1` causes startup to fail loudly — SessionRunner state is in-process and multi-worker routing is not yet supported.

## Prebuilt Pipelines

- **Blog Generation**: Researcher → Writer → Reviewer → Editor
- **Courseware Exam**: Parser (multimodal) → Analyzer → ExamGenerator → Reviewer

## Tech Stack

Python 3.12 · FastAPI · PostgreSQL · pgvector · Redis · LangGraph · Docker Compose

## Status

🚧 In development
