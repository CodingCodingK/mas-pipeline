## Why

Top-level chat agents (`assistant`, `coordinator`, `clawbot`) currently have no way to answer questions like "what project am I in?", "what runs did we do last week?", or "why did that run fail?". They can search documents via `search_docs` and read memory via `memory_read`, but have zero visibility into the operational state of the project itself — pipeline binding, document count, run history, per-node outcomes. Users routinely ask these questions in chat and the agent has to either hallucinate or refuse.

The data already exists in Postgres (`projects`, `documents`, `workflow_runs`, `agent_runs`). What's missing is a read-only tool surface that lets an agent fetch it safely without touching HTTP endpoints or raw SQL.

## What Changes

- Add three new built-in read-only tools in `src/tools/builtins/project_info.py`:
  - `get_current_project()` — return this project's name, pipeline binding, document count, and latest run summary. Named `get_current_project` (not `get_project_info`) to avoid collision with clawbot's existing explicit-param variant in `src/clawbot/tools/get_project_info.py`.
  - `list_project_runs(limit?, status?)` — return up to N recent `workflow_runs` for this project with per-run totals.
  - `get_run_details(run_id)` — return one run's `agent_runs` breakdown (role, status, tokens, duration, last-assistant preview).
- Register them in `src/tools/builtins/__init__.py:get_all_tools()`.
- Grant all three to `assistant.md`, `coordinator.md`, `clawbot.md` frontmatter. Pipeline sub-roles do NOT get them.
- All three tools resolve `project_id` from `ToolContext.project_id` only — never from LLM-supplied params. `get_run_details` additionally verifies the target run belongs to the caller's project and rejects cross-project access.

## Capabilities

### New Capabilities
- `project-info-tools`: Read-only tools that expose project metadata and run history to top-level chat agents.

### Modified Capabilities
<!-- none -->

## Impact

- **New code**: `src/tools/builtins/project_info.py` (~200 LOC), one registration line in `src/tools/builtins/__init__.py`.
- **Agent frontmatter**: `tools:` list updated on `agents/assistant.md`, `agents/coordinator.md`, `agents/clawbot.md`.
- **No schema changes**. Pure read-layer over existing tables.
- **No breaking changes**. Tools are additive; agents that don't list them in their `tools:` frontmatter are unaffected.
- **Security**: cross-project data leak is the only real risk. Mitigated by `project_id` coming exclusively from `ToolContext` and by `get_run_details` enforcing a `WHERE run.project_id = context.project_id` guard.
