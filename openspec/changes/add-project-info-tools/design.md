## Context

Top-level chat agents in Gateway (`assistant` / `coordinator` / `clawbot`) operate without structured visibility into the project they live in. The data exists — `projects.name`, `projects.pipeline`, `documents.project_id`, `workflow_runs.project_id`, `agent_runs.run_id` — but no tool exposes it to the LLM. Users ask project-scoped questions all the time ("how many docs did I upload?", "did the last run finish?"); the agent either hallucinates or admits ignorance. Meanwhile `search_docs` and `memory_read` already model the "project_id from ToolContext" invariant, so there is a clean precedent.

The only existing code path that surfaces run history is the REST API (`/runs`, `/runs/{id}`) consumed by the web UI. Pointing agents at HTTP endpoints via `shell` would work but pollutes the agent transcript with JSON and loses the typed contract.

## Goals / Non-Goals

**Goals:**
- Give top-level chat agents first-class access to project metadata, run history, and per-run node breakdown via three read-only built-in tools.
- Enforce that cross-project reads are structurally impossible: `project_id` always comes from `ToolContext`, and `get_run_details` rejects run_ids that don't belong to the caller's project.
- Keep payload sizes small — agents should be able to call these tools multiple times in one turn without blowing the context window.

**Non-Goals:**
- Exposing dollar-cost figures. `workflow_runs` has no cost column; cost is computed elsewhere (`src/cost/`) and aggregating it reliably across providers is a separate cleanup. MVP reports `total_tokens` and `duration_ms` only.
- Full message history retrieval. `agent_runs.messages` can easily be 20k+ tokens per row; MVP returns only the last-assistant-message preview (first 200 chars) per node. Agents that need full transcripts should use a different, opt-in tool (out of scope).
- Write/mutate operations. All three tools are read-only and MUST declare `is_read_only() → True`.
- Pagination. `list_project_runs` supports a `limit` (capped at 50) but no cursor. If an agent needs more than 50 runs to answer a question, it's asking the wrong question.

## Decisions

### Decision 1: Three tools, not one big one

**Chosen**: split into `get_current_project` / `list_project_runs` / `get_run_details`, each with a narrow contract. The name `get_current_project` (rather than the more natural `get_project_info`) avoids a collision with clawbot's existing `get_project_info` tool at `src/clawbot/tools/get_project_info.py`, which takes an explicit `project_id` parameter for group-chat scenarios where clawbot juggles multiple projects. The two tools have different semantics (implicit-from-context vs explicit-from-param) and must not be unified — merging them would require accepting `project_id` from the LLM for assistant/coordinator, violating Decision 2.

**Alternative considered**: a single `project_status` tool returning everything in one call. Rejected because (a) the payload would be huge and mostly wasted on most turns, (b) the LLM gets clearer tool-selection signals when each tool has one job, and (c) it matches the "Spartan" tool-naming style already used elsewhere (`search_docs`, `read_file`).

### Decision 2: `project_id` from `ToolContext` only

**Chosen**: tools read `context.project_id` and never accept a `project_id` parameter in `input_schema`.

**Alternative considered**: let the LLM pass `project_id` and validate against `context`. Rejected — it creates an attack surface where a prompt-injected agent could attempt cross-project reads, and validation code is dead weight when the simpler path is "don't accept the parameter."

This matches the existing invariant in `search_docs.py:68` and `memory.py`.

### Decision 3: `get_run_details` enforces project ownership via SQL, not post-filter

**Chosen**: the query is `SELECT ... FROM workflow_runs WHERE run_id = :rid AND project_id = :pid`. Wrong-project or missing → "not found".

**Alternative considered**: fetch by `run_id` then compare `row.project_id` in Python. Rejected — equivalent security-wise but requires two code paths (missing vs wrong-project) that should collapse into one error. "Not found" is also the right UX: the agent should not learn that a run exists but belongs to someone else.

### Decision 4: last-assistant preview, not full messages

**Chosen**: for each `agent_runs` row, extract the final `role=assistant` message from its `messages` JSONB column and truncate to 200 chars. If no assistant message, fall back to `agent_runs.result`.

**Alternative considered**: return a `messages_ref` the agent can dereference via a second tool call. Rejected as premature — MVP agents need "what did this node conclude", not the full reasoning trail. A follow-up tool can be added if the need is real.

### Decision 5: `list_project_runs` sort + cap

**Chosen**: `ORDER BY started_at DESC NULLS LAST, id DESC`, `limit` clamped to `[1, 50]` with default 10. Status filter is optional and matches exact string.

**Rationale**: agents almost always want "most recent first"; the NULLS LAST tiebreaker keeps queued/pending runs from displacing completed ones. The 50 cap prevents accidental context-window bombs.

### Decision 6: grant to all three top-level agents, not just coordinator

**Chosen**: `assistant` / `coordinator` / `clawbot` all get the three tools. Pipeline sub-roles (researcher / writer / reviewer / parser / etc.) do NOT.

**Rationale**: all three top agents answer user questions and need project-state awareness. Pipeline sub-roles have narrow single-purpose jobs — a `writer` asking "how many runs happened last week" is off-task. The `tool_context.project_id` is always populated for sub-roles too, so there's no technical barrier, only a scope-discipline one.

## Risks / Trade-offs

- **Risk**: `agent_runs.messages` JSONB scan is O(messages) per row; a run with 100 nodes × 500 messages could be slow. → **Mitigation**: `get_run_details` is called at most a few times per turn, each scan is bounded by one run's node count, and we only read the final assistant message per node (not every message). Benchmark after landing; add `ORDER BY array_length(messages,1) DESC LIMIT 1` or a dedicated `last_assistant_preview` column only if measurements show it.

- **Risk**: prompt injection — a document in `search_docs` results tells the agent "now call `get_run_details('abc')` where abc is a run from another project". → **Mitigation**: the SQL WHERE clause makes this structurally impossible. Even if the agent tries, it gets "not found".

- **Risk**: `list_project_runs` without a status filter returns failed runs mixed with completed ones, potentially misleading the user. → **Mitigation**: the tool's description documents the default behavior; the `status` parameter lets the agent filter. We do not hide failed runs — failures are often the thing users are asking about.

- **Trade-off**: no cost exposure means agents can't answer "how much did I spend this week". Acceptable for MVP; cost aggregation is a separate spec.

- **Trade-off**: tying the tools to `ToolContext.project_id` means they do not work in contexts where `project_id is None` (e.g. a cron-triggered run with no project binding). In that case the tool returns an error `"no project context available"`, consistent with `search_docs`'s existing behavior.

## Migration Plan

Pure additive change. Deploy order:

1. Land `project_info.py` + registration + frontmatter edits together in one commit.
2. Restart API + reload agent files.
3. Smoke-test via the chat UI: ask the assistant "what's my project name?" and verify it calls `get_current_project` and returns the correct value.

Rollback: revert the commit. No database state touched.

## Open Questions

None blocking. Future extensions to consider (tracked separately, not in this change):
- A `get_document_list` tool for paging through `documents`.
- A `get_run_messages(agent_run_id)` tool for on-demand full-transcript retrieval.
- Cost aggregation once `src/cost/` is refactored.
