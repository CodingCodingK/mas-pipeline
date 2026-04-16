# mas-pipeline

**English** | [中文](README.zh-CN.md)

> **Status: v0.1 — MVP (2026-04-14)** · free, open-source, primarily a learning project · docker one-command stack + REST + Web UI + group-chat bot wired end-to-end

A configurable Multi-Agent System engine for content production pipelines. Agents are Markdown files, pipelines are YAML DAGs, and the same workflow runs three ways — as a batch pipeline, as a chat session, or from a group-chat bot — with no per-front-end glue code.

<!-- HERO demo GIF / video — blog_with_review end-to-end including interrupt/resume.
     File: docs/images/hero-demo.gif  (1280×720, ≤6MB, 10–15s loop) -->
![mas-pipeline in action](docs/images/hero-demo.gif)

---

## v0.1 — MVP feature set

First tagged release. Engine, REST API, Web UI, docker stack, and group-chat gateway are wired end-to-end and pass an integration smoke test.

**Agent runtime** — streaming ReAct loop · provider-agnostic router (Anthropic / OpenAI / Gemini / DeepSeek / Qwen / Ollama) · append-only context compact with circuit breaker · **parallel tool calls in a single turn** · 11 built-in tools · sub-agents via `spawn_agent` with isolated transcripts · Markdown-defined skills · project-scoped persistent memory.

**Pipeline engine** — YAML DAG with dependency inference from `input` / `output` names · compiled to LangGraph 1.x with Postgres checkpointer · `interrupt: true` nodes for human review (approve / reject-with-feedback / edit-output) · substring-matched routing for branches.

**Three execution modes over one pipeline** — batch pipeline run · plain chat · autonomous chat (`coordinator` calls `spawn_agent` / `start_project_run`) · ClawBot group chat (Discord / QQ / WeChat) with intent routing and two-stage confirmation.

**Data & retrieval** — multimodal RAG (PDF / PPTX / DOCX / images) into pgvector · default local Ollama embedder, zero cloud key · server boots and degrades gracefully when embedder is offline.

**Security** — deny-list permission rules over every tool call · kernel sandbox for `ShellTool` (`bubblewrap` / `sandbox-exec`) · `PreToolUse` / `PostToolUse` / `UserPromptSubmit` hook points.

**Web UI** — React 18 + Tailwind SPA, 7 pages: projects dashboard, layered agent / pipeline / run tabs with source badges, chat with thinking blocks and sub-agent drawer, DAG editor (Monaco YAML ↔ React Flow, bidirectional), run detail with interrupt review, observability timeline.

**Deployment** — one-command `docker compose up` full stack · opt-in Prometheus + Grafana profile · 5 Prometheus signals · single-worker invariant enforced at startup.

**Deferred past v0.1:** multi-worker sticky routing, DB index tuning, cross-restart session recovery.

---

## Product tour

A quick tour of what the system actually does from the user's seat — the three ways in, what each one looks like in the browser, and how the pages stitch the whole thing together.

### A project at a glance

Everything lives inside a **project**: a container that holds source material, a default pipeline, a run history, and a scoped memory bank. You create one from the `ProjectsPage` dashboard, drop in PDFs / PPTX / DOCX / Markdown, and the RAG layer (`src/rag/`) chunks and embeds them into pgvector. `ProjectDetailPage` then fans out into tabs — `dashboard / pipeline / agents / runs / files / chat / observability` — so a single URL is enough to see and drive everything for one body of work.

<!-- DIAGRAM: three entry lanes → one SessionRunner → shared agent loop → tools / memory / telemetry
     File: docs/images/three-drivers.svg -->
![One engine, three drivers](docs/images/three-drivers.svg)

All three drivers below share the same `SessionRunner` (`_MODE_TO_ROLE = {"chat": "assistant", "autonomous": "coordinator", "bus_chat": "clawbot"}`), the same tool orchestrator, the same telemetry collector, and the same project-scoped memory surface. There is no second runtime path — the drivers are entrypoints into one loop.

### Driver 1 — Pipeline mode: DAG runs you can pause and approve

The headline driver. A pipeline is a YAML file under `pipelines/` that lists nodes; `src/engine/pipeline.py::load_pipeline` parses it, infers dependencies from `input` / `output` name matching (Kahn's algorithm for cycle detection), and `src/engine/graph.py` compiles it to LangGraph with `AsyncPostgresSaver` as the checkpointer. Each node is an agent turn that streams events live.

**How the pause-and-review mechanic actually works.** Any node flagged `interrupt: true` is split at compile time into two LangGraph nodes — `{name}_run` and `{name}_interrupt`. After `{name}_run` finishes, the interrupt node calls LangGraph's `interrupt({node, output})` primitive, which suspends the run and parks its full state inside the checkpointer. The run row flips to `status=paused` and surfaces `paused_at` + `paused_output` in the API. A reviewer then posts to `/runs/{run_id}/resume` with one of three actions:

| Action | Payload | Effect |
|---|---|---|
| `approve` | bare string or `{action: "approve"}` | Resume from the paused node, keep its output unchanged |
| `reject` | `{action: "reject", feedback: "..."}` | Resume with the rejection notes — downstream agents see them as context |
| `edit` | `{action: "edit", edited: "..."}` | Resume with the reviewer's replacement text as the node's output |

`resume_pipeline` loads the checkpoint via `checkpointer.aget(config)`, rebuilds the graph, and re-invokes it with `Command(resume=feedback)`. No polling, no state reconstruction — LangGraph's persistence layer does the heavy lifting.

**What you see in the browser.** `RunDetailPage.tsx` is where all of this surfaces. A colored status badge (`running / paused / completed / failed / cancelled`) sits above a **RunGraph** component that draws the pipeline as a live DAG — node rectangles fill in as each agent finishes. Click any node and **RunNodeDrawer** opens with the agent's transcript, tool calls, and token / cost stats. When the node is paused, the drawer grows three buttons — approve, reject, edit — and `edit` pops a Monaco editor pre-loaded with the paused output so the reviewer can rewrite it in place. The page keeps an **SSE connection** to `/projects/{pid}/pipelines/{name}/runs?stream=true`, so `pipeline_start / node_start / node_end / pipeline_paused / pipeline_end` events fill the timeline the moment they happen (15 s heartbeat, drop-oldest on slow consumers).

**Authoring pipelines.** `PipelineEditorPage.tsx` is where new workflows get written. Left pane: pipeline list with clone / new buttons. Right pane: a **Monaco YAML editor** alongside a **PipelineGraph** canvas (React Flow laid out by dagre) that renders the parsed YAML as a readable DAG. Authors edit the YAML; everyone else reads the graph.

**The Assistant helper alongside.** Every project ships with a chat page manned by a read-only `assistant` agent (`agents/assistant.md`, `model_tier: light`, `readonly: true`, `entry_only: true`, `max_turns: 8`). It isn't there to generate content; it's there to answer questions about the project itself. Its toolbelt is deliberately narrow — `get_current_project`, `list_project_runs`, `get_run_details`, `search_docs` (RAG over uploaded material), `web_search` as fallback, and `memory_read` / `memory_write`. You can ask it *"what did run #42 conclude?"* or *"which chapter of the uploaded deck talks about attention heads?"* and it will walk the project state for you. Because it's `entry_only`, it can't be spawned as a sub-agent; because it's `readonly`, it can never accidentally kick off a new pipeline run while answering.

### Driver 2 — Autonomous chat: the Coordinator fans out sub-agents for you

The second driver is the same `ChatPage.tsx` with the **mode dropdown flipped from `chat` to `autonomous`**. URL, session model, SSE stream — all identical; what changes is the role: `_MODE_TO_ROLE["autonomous"] = "coordinator"`. The conversation is now backed by `agents/coordinator.md` — `model_tier: strong`, `entry_only: true`, and a tool whitelist that includes **`spawn_agent`** on top of the same project-info tools the assistant has.

The Coordinator's job is to decompose a natural-language ask, fan it out across specialist sub-agents, and stitch their results back together. Say *"Draft a 1500-word post on HTTP/3 multiplexing and have a reviewer double-check the facts"* — the Coordinator calls `spawn_agent(role="researcher", task_description=...)`, which returns *immediately* with an `agent_run_id` while the researcher runs in a background task. The researcher's completion is later delivered to the Coordinator's conversation as an XML `<task-notification>` block (see Under the hood → Sub-agents for the isolation invariant). The Coordinator reads the notification, spawns a writer against the research, reads that back, then spawns a reviewer. Each sub-run shows up in the chat as a task-notification card; clicking one opens **AgentRunDetailDrawer** with the sub-agent's full transcript, per-run stats as badges, and role-colored message rows — so you can drill into the collaboration without it cluttering the main thread.

You get the multi-agent story of a pipeline without having to write the YAML first; if a pattern becomes repeatable, it's ready to be lifted into an actual `pipelines/*.yaml` file.

### Driver 3 — ClawBot: the same engine inside Discord / QQ / WeChat

The third driver pushes everything out into a group-chat room. `src/bus/gateway.py` hosts a **Gateway service** (a separate container in `docker-compose.yml`); inbound messages land in `Gateway.process`, get matched to a session keyed on `channel + chat_id`, get appended to the Conversation via `append_message`, and wake a `SessionRunner` with `mode=bus_chat`. The role resolves to `clawbot` (`agents/clawbot.md`, `model_tier: strong`), and it gets an **11-tool gateway toolbelt** on top of the shared pool:

| Tool | Purpose |
|---|---|
| `list_projects` | Enumerate the projects visible to this chat |
| `get_project_info` | Name, pipeline, doc count, latest run for one project |
| `search_project_docs` | RAG search scoped to one project |
| `start_project_run` | **Stage 1** of two-stage confirm — drops a pending run into `PendingRunStore` (10 min TTL, single slot) |
| `confirm_pending_run` | **Stage 2** — reads the pending slot, creates the `workflow_runs` row, launches execution in the background |
| `cancel_pending_run` | Discard the pending slot before it fires |
| `cancel_run` | Abort a run that's already running or paused |
| `get_run_progress` | Query live status / current node / last event |
| `resume_run` | Surface the approve / reject / edit review flow from inside a chat turn |
| `persona_write` | Full-file replace of this chat's `SOUL.md` override |
| `persona_edit` | Unique-match string patch on this chat's `SOUL.md` |

**Two-stage confirmation** exists because kicking off a pipeline costs real money. The flow looks like this:

```
user:      "run blog_with_review on project 5"
clawbot:   → start_project_run(project_id=5, pipeline="blog_with_review", inputs={...})
           "I'm about to start blog_with_review on project #5 with inputs X — y/n?"
user:      "yes"
clawbot:   → confirm_pending_run()  → creates workflow_runs row, launches pipeline
           "run #42 started"
```

A `no` (or silence past the 10-min TTL) routes to `cancel_pending_run` instead. Same-turn double-calls to `start_project_run` are rejected so the bot can't double-fire; changing parameters mid-confirmation is a fresh `start_project_run` that overwrites the pending slot.

**Progress pushback.** Once a pipeline is running, `src/clawbot/progress_reporter.py` subscribes to the same EventBus the Web UI listens to — but instead of driving SSE, it publishes `OutboundMessage`s back to the originating channel: `run_start` → *"run #42 started"*, `interrupt` → *"run #42 paused at `writer`, reply `/resume 42 approve|reject:...|edit:...`"*, `done` → *"run #42 finished in 97 s"*. The `/resume` command is parsed by the Gateway directly (bypassing ClawBot entirely) so a user can approve a paused run without paying for a full model turn.

**Per-chat persona.** The baseline `config/clawbot/SOUL.md` defines the bot's default voice. Any chat can override it at `config/clawbot/personas/<channel>/<chat_id>/SOUL.md` (32 KB cap) — *"reply in English only"*, *"call me 大佬"*, *"never use emojis"*. `channel` and `chat_id` come from `ToolContext`, never from tool parameters, so one chat can't clobber another's SOUL by construction.

<!-- VIDEO: end-to-end demo driving blog_with_review from all three surfaces.
     Storyboard: (1) Pipeline mode — upload material, Start, node pauses, edit in RunNodeDrawer, resume, final post renders. (2) Autonomous chat — Coordinator fans out researcher → writer → reviewer, task-notifications drill into AgentRunDetailDrawer. (3) ClawBot — group asks for a run, two-stage confirm, progress pushback, /resume from chat.
     File: docs/images/demo-three-drivers.mp4 (target 60–90 s) -->
[▶ Watch the end-to-end demo — pipeline mode, autonomous chat, and ClawBot driving the same workflow](docs/images/demo-three-drivers.mp4)

### Shape your own pipeline

The shipped pipelines (`blog_generation`, `blog_with_review`, `courseware_exam`, `test_linear`, `test_parallel`) are meant as starting points. Inside `PipelineEditorPage` you drag in a new node, pick a role from the `agents/` folder, wire inputs to outputs by name, and flip `interrupt: true` on any step you want to review by hand — all of it round-trips through the Monaco YAML pane so the file on disk stays authoritative. Pair that with **project-scoped memory** (see Under the hood) — style guides, reviewer preferences, the things a project "just knows" — and the same `blog_with_review` pipeline produces subtly different results for a research team and a marketing team without either one writing a new agent.

### Built in the open, spec-first

v0.1 was built entirely inside Claude Code using an OpenSpec-driven workflow — every change went through a `propose → design → spec delta → tasks → archive` cycle before landing, and the full spec history lives under `openspec/`. If you're curious how a spec-first agentic workflow scales to a real project, the archives are the primary document.

---

## Under the hood

Six load-bearing pieces make the three drivers above sharp instead of fragile: a streaming agent loop with concurrency-safe parallel tool dispatch, a two-layer memory design, a hard isolation invariant around sub-agents, three different compact strategies stacked on top of each other, a three-lane safety net around every tool call, and a telemetry collector that feeds both the in-app dashboard and Prometheus from the same event source.

### Streaming loop, parallel tool calls

The agent loop (`src/agent/loop.py::agent_loop`) is an `AsyncIterator[StreamEvent]`. Nine event types flow through it — `text_delta`, `thinking_delta`, `tool_start`, `tool_delta`, `tool_end`, `tool_result`, `usage`, `done`, `error` — normalized across OpenAI, Anthropic, Gemini, DeepSeek, Qwen, and Ollama by the adapters in `src/llm/`. Every event is yielded the moment the adapter produces it.

`SessionRunner` (`src/engine/session_runner.py`) sits between the loop and the outside world: it owns the `AgentState`, fans events out to SSE subscribers through a bounded queue (capacity 100, drop-oldest on slow consumers), and wakes the loop via an `asyncio.Event` whenever a new message lands in the conversation. The Web UI consumes the same stream, so characters appear on the page as the model writes them.

When the model returns N tool calls in one turn, `src/tools/orchestrator.py::partition_tool_calls` splits them into **consecutive safe / unsafe batches** and runs each safe batch through a single `asyncio.gather` bounded by a semaphore (`_MAX_CONCURRENCY = 10`). A tool opts out of parallelism by returning `False` from `is_concurrency_safe()` — `write_file` does this because two concurrent writes to the same path race, while `read_file`, `search_docs`, `web_search`, and `rag_search` stay parallel. Results are keyed by `tc.id` and reassembled in their original order before being handed back to the model, so the transcript stays deterministic even though execution fanned out.

Crucially, **permission checks, `PreToolUse` / `PostToolUse` hooks, and telemetry run per call**, not per batch — every parallel call shows up on the Observability timeline with its own duration bar. In practice, a RAG-heavy writer turn that used to run three searches sequentially now finishes in the cost of the slowest one.

### Memory in two layers

Memory is split along behavioral vs factual lines — each layer has its own store, its own tools, and its own scope.

**Layer 1 — file-based persona (ClawBot only).** ClawBot's personality lives in `config/clawbot/SOUL.md` as a baseline. Any chat can override it at `config/clawbot/personas/<channel>/<chat_id>/SOUL.md` — one file per Discord/QQ/WeChat chat, capped at 32 KB. `src/clawbot/factory.py::create_clawbot_agent` calls `load_soul_bootstrap(channel, chat_id)` at agent-creation time; `src/clawbot/prompt.py::resolve_soul_path` checks for the override and falls back to the baseline if absent. Two tools mutate it: `persona_write` (full-file replace, for structural changes) and `persona_edit` (unique-match string replace, for incremental tweaks). `channel` and `chat_id` come from `ToolContext`, never from parameters, so one chat can't touch another's SOUL by construction.

**Layer 2 — project-scoped DB memory.** Factual memories live in a PostgreSQL `memories` table (`src/models.py::Memory`), keyed by `project_id`. Every record has one of four types enforced in `src/memory/store.py::VALID_TYPES`:

| Type | Holds |
|---|---|
| `user` | Who the user is — role, expertise, what they care about |
| `feedback` | Guidance the user has given about how to work (corrections + validated approaches) |
| `project` | Facts about the ongoing work — goals, decisions, constraints, deadlines |
| `reference` | Pointers to external systems — dashboards, trackers, docs |

The interesting part is **selection**. `src/memory/selector.py::select_relevant` lists all memories for the project, but hands the light-tier LLM (`route("light")`) only the `(id, type, name, description)` tuples — the expensive `content` bodies never reach the judge. The judge returns a JSON array of relevant IDs; only those bodies are fetched back from PG and injected into the main agent's context (default `limit=5`). A project can accumulate hundreds of memories without the main-tier prompt growing, and the recall decision costs a fraction of a main-tier turn.

Because the DB layer is project-scoped and wired through `memory_read` / `memory_write` as first-class tools, chat, autonomous chat, pipeline runs, and ClawBot all read and write the same surface — a writer agent in a pipeline tomorrow sees what a chat session taught yesterday.

### Sub-agents, kept at arm's length

`spawn_agent(role=..., task=...)` is how the engine does multi-agent fan-out from inside a single conversation. It forks a background run with its own message log, its own compact boundary, and its own tool budget. The call **returns immediately** — the parent keeps working — and the child's completion is delivered back as a task-notification message on the parent's conversation. The parent `SessionRunner` is woken via an `asyncio.Event`, with a best-effort `LISTEN/NOTIFY` signal keeping the door open for future multi-worker deployments.

What the parent sees is a compact XML block — `id / role / status / tool-use-count / total-tokens / duration-ms / result` — in that exact order so the main-tier model can cost-gate on the prefix before paying to parse the body. The full sub-transcript lives in `agent_runs.messages` and is drillable from the chat thread: click a task notification and the `AgentRunDetailDrawer` opens with the complete transcript, per-run stats as badges, and role-colored message rows.

The **isolation invariant** is load-bearing. Only two code paths in the whole project touch `agent_run.messages`: the write path inside `src/agent/runs.py`, and the REST read path in `src/api/runs.py` (used by the drawer). No context builder, no prompt assembler, no tool implementation ever reads the sub-agent's transcript. This means the parent's context window cannot be polluted with a child's internals — the parent pays for the summary line only, not for the child's reasoning. Combined with append-only compact, a coordinator can orchestrate dozens of sub-runs over a long conversation without the parent's prompt growing unboundedly.

### Compact in three passes

`src/agent/compact.py` runs three different compact strategies, each fired under different conditions. All three are **append-only** against the persistence log — the full history stays in PG for replay and audit; only the slice the model sees shrinks.

**1. `micro_compact` — every turn, no LLM.** The cheapest pass. On entry to each agent loop iteration, older tool-result messages beyond the most recent `keep_recent` (default 3) have their `content` replaced with `[Old tool result cleared]`. A read-heavy researcher turn that fired ten `search_docs` calls keeps the three most recent bodies intact; the other seven shrink to a marker string. Free, deterministic, needs no summarizer call.

**2. `auto_compact` — at 85% of context, LLM summarize.** Triggered when `estimate_tokens(...) > ctx_window * autocompact_pct` (`autocompact_pct=0.85` by default). It computes a split point that keeps roughly the last 30% of the context window as recent messages, hands the older slice to the main adapter with a summarization system prompt, and appends `{summary_msg, boundary_msg}` to the tail. The next turn's prompt is sliced tail-to-head from `is_compact_boundary`, so the model effectively sees `[summary] + recent messages`, while PG keeps everything.

**3. `reactive_compact` — on `context_length_exceeded`, LLM summarize harder.** The safety net. If the adapter call still raises a context-overflow error despite the 85% threshold (CJK under-counting, long tool outputs landing in one turn), the loop catches the exception once per runner and re-runs the compact path with a tighter 20% budget. Same append-only shape, just more aggressive.

Several cross-cutting invariants hold for all three:

- **Cascading compacts compose.** Each compact operates on the slice after the *latest* boundary (`_latest_boundary_end`), so a new summary subsumes the previous one without re-summarizing it — no quadratic blow-up on long sessions.
- **Summarizer PTL retry.** If the summarizer call itself trips `prompt_too_long`, `_summarize_with_retry` drops the oldest half of the older blob and retries once before giving up — mirrors Claude Code's `truncateHeadForPTLRetry`.
- **3-strike circuit breaker.** Three consecutive compact failures flip `state.compact_breaker_tripped` and silently skip compact for the rest of the runner's lifetime, so a bad stretch can't cascade into a runaway loop.
- **Runtime slicing is load-bearing.** `agent_loop` passes messages through `slice_messages_for_prompt` at both the adapter call and the `estimate_tokens` measurement, so the compacted view is what's counted *and* what's sent — a mismatch here would make auto_compact fire every turn and grow the list unboundedly.

<!-- IMAGE: append-only compact timeline — messages grow → summary + boundary appended → sliced view.
     File: docs/images/compact-timeline.svg -->
![Append-only compact](docs/images/compact-timeline.svg)

### Safety: permissions, sandbox, hooks

Three orthogonal safety layers wrap every tool call.

**Permissions (`src/permissions/`).** A rule engine with three modes — `BYPASS` (allow all, used by smoke tests), `NORMAL` (evaluate rules → `allow` / `deny` / `ask`), `STRICT` (every `ask` becomes a `deny` for unattended runs). Rules are deny-first and match on tool name plus a parameter glob — `write_file` against `.env*`, `shell` against `rm -rf*`, `exec` against `curl*|*sh*`. Sub-agents **inherit the parent's deny rules** by prepending them to their own set, so a `coordinator` can never spawn a `researcher` with broader powers than itself. The result type is `PermissionResult{action, reason, matched_rule}`, and the orchestrator surfaces the matched rule in the tool-result so the model learns *why* a call was denied.

**Sandbox (`src/sandbox/`).** Command-running tools (`exec`, `shell`) are wrapped in an OS-native sandbox before they execute. On Linux that's **`bubblewrap`** — `--unshare-all`, `--ro-bind` for the base filesystem, `--bind` for explicit writable paths, a minimal `/proc /dev /tmp`. On macOS it's **`sandbox-exec`** with a generated `.sbpl` profile — deny-by-default plus targeted `(allow file-write* (subpath ...))` clauses. On Windows it falls through to a passthrough. The wrapper distinguishes its own failures (`bwrap: exec failed`) from the user command's failures so the model sees clean errors, not prefix junk.

**Hooks (`src/hooks/`).** A lightweight event bus the tool orchestrator and session runner fire into at well-defined points: `pre_tool_use`, `post_tool_use`, `post_tool_use_failure`, `session_start`, `session_end`, `subagent_start`, `subagent_end`, `pipeline_start`, `pipeline_end`. Each hook can return `allow`, `deny`, or `modify` with an `updated_input` dict — deny wins over everything, modify mutates the tool input before the call, and `additional_context` lines get appended to the tool result so the model sees them. Hook exceptions are logged and swallowed (permissive by design); a broken hook can never break the turn.

### Telemetry you can watch live

Observability isn't bolted on — the collector is invoked directly from inside the tool orchestrator and agent loop, so turning it off would be more work than leaving it on. Every agent turn emits `StreamEvent`s that flow into a bounded async queue, drained by a background `_writer_loop` that batches inserts into the `telemetry_events` table.

The collector tracks five event families — **llm_call** (tokens / latency / finish_reason per `{provider/model}`), **tool_call** (name / args preview / duration / success), **agent_turn** (role / input preview / output preview / stop reason), **pipeline_event** (start / node_start / node_end / paused / end), and **error** (source / type / message). Context propagation is handled by `contextvars` — `current_turn_id`, `current_spawn_id`, `current_run_id`, `current_session_id`, `current_project_id` — which `asyncio.create_task` snapshots automatically, so a sub-agent's telemetry rows already know which parent turn they belong to without any explicit plumbing. Cost is computed per event against `config/pricing.yaml`, which maps `{provider/model}` → `$/1K input + $/1K output + $/1K thinking`.

`ObservabilityPage.tsx` reads from `/api/telemetry/*` endpoints and draws the lot with Recharts — a timeline of LLM calls, a tool-call histogram, stacked token cost over time, and a per-session conversation view. Three subtabs (`conversations / aggregates / timeline`) let you slice by session, project, or date window.

The `/metrics` endpoint additionally exposes five Prometheus signals — `sessions_active`, `workers_running`, `pg_connections_used`, `sse_connections`, `messages_total`. The three registry-backed gauges use **pull callbacks** against the real session registry, the jobs registry, and `engine.pool.checkedout()`, so there is no drift-prone inc/dec path — the numbers always reflect reality on scrape. An opt-in compose profile (`--profile monitoring`) brings up Prometheus + Grafana with an auto-provisioned dashboard under `deploy/grafana/`.

<!-- IMAGE: Observability page + Grafana dashboard, 2×1 composite.
     File: docs/images/observability.png -->
![Session telemetry and Grafana dashboard](docs/images/observability.png)

### Skills and MCP, in passing

Two smaller integration points, mentioned for completeness:

- **Skills** — reusable Markdown task templates under `skills/`. The `skill` tool takes a name + parameters and executes the template as a forked agent run, returning the fork's final output. Used for narrower repeatable workflows that don't need a full pipeline.
- **MCP** — stdio MCP servers configured per agent in YAML frontmatter (ships with `@modelcontextprotocol/server-github`). `SessionRunner` starts the manager before agent creation and merges the MCP tool set into the agent's tool pool for that session. Unset credentials degrade gracefully.

---

## Architecture

```
src/
  agent/       ReAct loop · state · context builder · append-only compact
  llm/         Multi-provider adapter + tier/prefix router
  engine/      Pipeline engine · LangGraph compile · SessionRunner · registry
  tools/       Tool ABC · concurrency-aware orchestrator · 11 built-ins
  permissions/ Allow/deny rules · param normalization
  sandbox/     bubblewrap / sandbox-exec wrappers
  mcp/         stdio MCP server manager
  rag/         Parsers · chunker · embedder · pgvector retriever
  memory/      Project-scoped KV store + light-tier relevance judge
  skills/      Forked-run skill executor
  hooks/       PreToolUse · PostToolUse · UserPromptSubmit
  events/      PG-backed event bus
  streaming/   SSE helpers + StreamEvent encoding
  notify/      Per-chat SSE notification endpoint
  telemetry/   Token · latency · tool-call · cost collector
  bus/         ClawBot gateway service
  clawbot/     Group-chat bot factory, persona, 11 gateway tools
  api/         12 FastAPI routers
  main.py      Lifespan, startup validation, single-worker guard

agents/        11 Markdown agent roles
pipelines/     5 YAML pipelines (blog × 2, courseware_exam, tests × 2)
skills/        Markdown skill templates
config/        settings.yaml · settings.local.yaml · pricing.yaml
deploy/        prometheus.yml · grafana provisioning
scripts/       test_e2e_smoke.py · init_db.sql · migrations
web/           Vite + React 18 + TS SPA (7 pages, ~8400 LoC)
openspec/      Spec archives from the OpenSpec-driven dev workflow
```

Rough size: agent runtime ~1400 LoC, pipeline + session engine ~2400 LoC, frontend ~8400 LoC.

---

## Tech stack

### Backend (Python 3.12)

| Layer | Libraries |
|---|---|
| **Web framework** | FastAPI 0.115+ · uvicorn[standard] · python-multipart · websockets |
| **Data validation** | Pydantic 2.10+ · pydantic-settings 2.7+ |
| **Database / ORM** | SQLAlchemy 2.0 (async) · psycopg 3 · PostgreSQL 16 + pgvector |
| **Cache / pubsub** | Redis 5 + hiredis |
| **Workflow** | LangGraph 1.x · `langgraph-checkpoint-postgres` 3.x |
| **LLM clients** | httpx (direct, no vendor SDKs) — Anthropic, OpenAI-compatible, Gemini, DeepSeek, Qwen, Ollama |
| **Token accounting** | tiktoken 0.8+ |
| **Multimodal ingest** | PyMuPDF · pymupdf4llm · python-pptx · python-docx |
| **Observability** | prometheus-client 0.20+ · rich |
| **YAML / config** | PyYAML · `${VAR:default}` substitution |

### Frontend (Node 20)

| Layer | Libraries |
|---|---|
| **Framework** | React 18.3 · TypeScript 5.6 · Vite 5.4 · React Router 6.26 |
| **Styling** | Tailwind CSS 3.4 · tailwindcss-animate · PostCSS |
| **Chat primitives** | `@assistant-ui/react` · `react-markdown` + `remark-gfm` |
| **DAG editor** | `@xyflow/react` · `@dagrejs/dagre` · `yaml` (bidirectional sync) |
| **Code editor** | `@monaco-editor/react` |
| **Charts** | Recharts |
| **Testing** | Vitest · @testing-library/react |

### Infrastructure & ops

| Area | Tool |
|---|---|
| **Container orchestration** | Docker Compose (6 base + 2 monitoring) · multi-stage builds |
| **Web proxy** | nginx (SPA history fallback + `/api/` reverse proxy + SSE passthrough) |
| **Monitoring (opt-in)** | Prometheus 2.54 · Grafana OSS 10.4 (auto-provisioned) |
| **Sandbox** | `bubblewrap` (Linux) · `sandbox-exec` (macOS) · passthrough (Windows) |
| **MCP transport** | stdio (Node `npx` servers) |
| **Embedding (default)** | Ollama + `nomic-embed-text` (768-dim, local) |
| **Web search** | Tavily API |

### Dev tooling

| Purpose | Tool |
|---|---|
| **Change management** | **OpenSpec** (spec-driven workflow, executed inside **Claude Code**) |
| **Testing** | pytest 8.3 · pytest-asyncio · pytest-cov |
| **Linting** | ruff 0.8 · mypy 1.13 (strict) |
| **Integration smoke** | `scripts/test_e2e_smoke.py` + `docker-compose.smoke.yaml` |
| **Platform helpers** | `start.bat` / `stop.bat` (Windows) · `scripts/start.sh` |

---

## Quick start

**Prerequisites:** Docker & Docker Compose v2 · Git · (optional, for local dev) Python ≥ 3.12 · Node ≥ 20

```bash
# 1. Clone & configure
git clone <repo-url> mas-pipeline && cd mas-pipeline
cp .env.example .env                              # fill in ≥1 LLM provider key
cp config/settings.local.yaml.example config/settings.local.yaml  # optional: override model tiers

# 2. Launch the stack
docker compose up --build -d                      # postgres + redis + ollama + api + gateway + web
# Windows: start.bat
```

Open http://localhost (UI) · http://localhost/api/docs (OpenAPI) · http://localhost/metrics (Prometheus)

**Required env** (`.env`) — at least one of:

```ini
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
DEEPSEEK_API_KEY=sk-...
TAVILY_API_KEY=tvly-...          # optional, enables web_search tool
```

**Optional model-tier override** (`config/settings.local.yaml`):

```yaml
# Example: override the default tiers with specific models
models:
  strong: claude-sonnet-4-6      # researcher, reviewer, clawbot
  medium: deepseek-chat          # writer, analyzer, exam_generator
  light:  gpt-4o-mini            # summarization, memory relevance judge
```

The router validates every tier at startup — **missing API keys refuse boot** instead of 401-ing at runtime.

**Optional extras**

```bash
ollama pull nomic-embed-text                      # enable RAG (local, zero cloud key)
docker compose --profile monitoring up -d         # Prometheus :9090 + Grafana :3000 (admin/admin)
pytest scripts/test_e2e_smoke.py                   # end-to-end integration test
```

---

## Prebuilt pipelines

| Pipeline | Shape | Notes |
|---|---|---|
| `blog_generation` | Researcher → Writer → Reviewer → Editor | Baseline linear flow |
| `blog_with_review` | Researcher → Writer (interrupt) → Reviewer | Reference for approve / reject / edit HIL |
| `courseware_exam` | Parser (multimodal) → Analyzer → ExamGenerator → Reviewer | Ingests PPTX / PDF |
| `test_linear` / `test_parallel` | synthetic | Regression fixtures |

Add a new pipeline by dropping a YAML into `pipelines/` — or author one inside the app with the DAG editor.

---

## License

MIT
