"""Context builder: role file parsing, system prompt construction, messages assembly."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from src.skills.types import SkillDefinition


def parse_role_file(path: str) -> tuple[dict, str]:
    """Parse an agent role file, separating YAML frontmatter from body.

    Returns (metadata_dict, body_string).
    If no frontmatter, returns ({}, full_text).
    """
    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1])
            return (fm or {}), parts[2].strip()
    return {}, text.strip()


def build_system_prompt(
    role_body: str,
    project_root: str | None = None,
    memory_context: str | None = None,
    skill_definitions: list[SkillDefinition] | None = None,
) -> str:
    """Build system prompt by concatenating layers: identity, role, memory, skill."""
    layers: list[str | None] = [
        _identity_layer(project_root),
        _role_layer(role_body),
        _memory_layer(memory_context),
        _skill_layer(skill_definitions),
    ]
    return "\n\n".join(layer for layer in layers if layer)


def build_messages(
    system_prompt: str,
    history: list[dict],
    user_input: str,
    runtime_context: dict | None = None,
) -> list[dict]:
    """Assemble OpenAI-format messages: [system, ...history, user].

    If runtime_context is provided, it is appended to the system prompt
    as a '# Runtime Context' section.

    Compact boundary slicing (align-compact-with-cc): before emitting the
    history portion, scan tail-to-head for the most recent message with
    `metadata.is_compact_boundary=True`. If found, emit the paired
    `is_compact_summary` entry (metadata stripped) as the first user turn,
    then emit only messages AFTER the boundary marker. Messages before the
    boundary remain in PG for audit but are invisible to the model. When no
    boundary is present, emit the full history as-is (back-compat).
    """
    prompt = system_prompt
    if runtime_context:
        ctx_lines = "\n".join(f"- {k}: {v}" for k, v in runtime_context.items())
        prompt += f"\n\n# Runtime Context\n{ctx_lines}"

    sliced_history = _slice_at_compact_boundary(history)

    return [
        {"role": "system", "content": prompt},
        *(_strip_metadata(msg) for msg in sliced_history),
        {"role": "user", "content": user_input},
    ]


def slice_messages_for_prompt(messages: list[dict]) -> list[dict]:
    """Return the model-visible slice of an in-memory message list.

    Used by agent_loop to strip metadata and apply compact-boundary slicing
    before handing messages to the adapter. state.messages may contain
    pre-boundary entries retained for PG audit; those must not reach the LLM.
    """
    sliced = _slice_at_compact_boundary(messages)
    return [_strip_metadata(msg) for msg in sliced]


def _slice_at_compact_boundary(history: list[dict]) -> list[dict]:
    """Find the most recent compact boundary and emit the visible slice.

    Visible slice = the paired summary entry + every message AFTER the
    boundary. The boundary marker itself is NOT emitted.
    """
    boundary_idx: int | None = None
    for i in range(len(history) - 1, -1, -1):
        meta = history[i].get("metadata") or {}
        if meta.get("is_compact_boundary"):
            boundary_idx = i
            break

    if boundary_idx is None:
        return history

    summary_entry: dict | None = None
    if boundary_idx > 0:
        prev = history[boundary_idx - 1]
        prev_meta = prev.get("metadata") or {}
        if prev_meta.get("is_compact_summary"):
            summary_entry = {"role": "user", "content": prev.get("content", "")}

    tail = history[boundary_idx + 1 :]
    if summary_entry is not None:
        return [summary_entry, *tail]
    return tail


def _strip_metadata(msg: dict) -> dict:
    """Return a copy of msg without the `metadata` key.

    Adapters expect plain OpenAI-format dicts and should never see metadata.
    """
    if "metadata" not in msg:
        return msg
    return {k: v for k, v in msg.items() if k != "metadata"}


# --- Layers ---


def _identity_layer(project_root: str | None) -> str:
    parts = [
        "# Environment",
        f"- OS: {platform.system()} {platform.release()}",
        f"- Python: {sys.version.split()[0]}",
    ]
    if project_root:
        parts.append(f"- Project root: {project_root}")
    return "\n".join(parts)


def _role_layer(role_body: str) -> str | None:
    return f"# Role\n{role_body}" if role_body else None


_MEMORY_DRIFT_CAVEAT = (
    "These memories were written in past sessions and may be stale. "
    "Before relying on a remembered fact (file path, function name, flag, "
    "decision, status), verify it against the current code or data. "
    "If a memory conflicts with what you observe now, trust the current "
    "observation — the memory is wrong and should be updated, not acted on."
)


# Project memory behavioural guide. Injected when the agent has memory tools.
# Adapted from Claude Code's memdir prompt (memoryTypes.ts + memdir.ts) —
# same 4-type taxonomy, same What-NOT-to-save list, same drift caveat, same
# dedup-before-write rule. Differences: our memories live as rows in a
# project-scoped PG table, reached through memory_read / memory_write tools
# (not files + a MEMORY.md index). project_id is attached automatically.
_MEMORY_GUIDE = """\
# Project memory

You have project-scoped memory through `memory_read` (actions: `list`, `get`)
and `memory_write` (actions: `write`, `update`, `delete`). project scope is
attached automatically — you never pass a project id. If the user asks you
to remember or forget something, do it immediately.

## Types of memory

<types>
<type>
  <name>user</name>
  <description>Facts about the user's role, expertise, and personal preferences about how they want to be helped.</description>
  <when_to_save>When you learn any durable detail about who the user is or how they prefer to work.</when_to_save>
  <example>
  user: 我是资深开发，解释的时候可以跳过基础概念
  assistant: [saves user memory: 用户为资深开发者 — 解释时默认跳过入门级术语铺垫]
  </example>
</type>
<type>
  <name>feedback</name>
  <description>Guidance the user has given on how to approach work — corrections AND confirmations. Save both: corrections stop mistakes, confirmations lock in validated choices.</description>
  <when_to_save>When the user corrects your output or explicitly confirms a non-obvious choice worked. Include *why* so edge cases can be judged later.</when_to_save>
  <body_structure>Lead with the rule, then **Why:** and **How to apply:**.</body_structure>
  <example>
  user: 这份试卷客观题太多了，以后填空和简答至少各占 30%
  assistant: [saves feedback memory: 题型结构 — 填空 ≥30%, 简答 ≥30%, 客观题 ≤40%. **Why:** 用户反馈客观题过多, 主观题不足. **How to apply:** courseware_exam 及后续出题类 pipeline 默认结构]
  </example>
</type>
<type>
  <name>project</name>
  <description>Ongoing work, goals, stakeholders, deadlines, or decisions tied to this project that are not derivable from files or git history.</description>
  <when_to_save>When you learn who is doing what, why, or by when. Convert relative dates to absolute dates (e.g., "周四" → "2026-04-16").</when_to_save>
  <body_structure>Lead with the fact, then **Why:** and **How to apply:**.</body_structure>
  <example>
  user: 这学期的课件统一用新教材第三册, 前两册不用了
  assistant: [saves project memory: 当前学期使用新教材第三册；第一、二册停用. **Why:** 教材版本切换. **How to apply:** RAG 检索和出题时过滤掉旧教材范围的 chunk]
  </example>
</type>
<type>
  <name>reference</name>
  <description>Pointers to information living outside this project's uploaded files — external systems, URLs, shared drives the user mentions.</description>
  <when_to_save>When the user mentions an external resource that may be needed again.</when_to_save>
  <example>
  user: 我们的素材都在公司共享盘 S:/materials/2026/ 下
  assistant: [saves reference memory: 项目素材根目录 = S:/materials/2026/]
  </example>
</type>
</types>

## What NOT to save

- Code patterns, file structure, anything derivable by listing project files
- Debug traces, failed attempts, ephemeral task state
- Content already captured in the current conversation
- Bulk activity summaries — if asked to save a log, ask what was *surprising*; save only that

These exclusions apply even when the user explicitly asks you to save.

## How to save (dedup first)

**Before `action="write"`, call `memory_read action="list"` and scan for
existing entries on the same topic.** If one exists, use `action="update"`
with its `memory_id` to overwrite or extend — do NOT create a duplicate.
Only `write` when nothing covers the topic.

Keep `name` short and specific (e.g. `test_question_ratio`, not
`feedback_2026_04_14`). Keep `description` to one sentence with enough
keywords that a future query can match it — it is the hook the recall
selector sees, not just documentation.

## When to use memory

- At the start of a task, or when the user references past work, scan the
  memory list for preferences / project context that should shape your approach.
- If the user says to *ignore* memory, proceed as if the list were empty —
  do not cite or compare against remembered facts."""


def _memory_layer(memory_context: str | None = None) -> str | None:
    """Return memory guide + current project memories.

    `memory_context` semantics:
      - None: agent has no memory tools → no memory layer at all.
      - "" (empty): agent has memory tools but project has no memories yet →
        inject the guide + an empty-state hint (so the agent still knows how
        to save its first memory).
      - non-empty str: agent has memory tools and the formatted list is
        provided → inject guide + drift caveat + list.
    """
    if memory_context is None:
        return None
    if not memory_context.strip():
        return (
            f"{_MEMORY_GUIDE}\n\n"
            "## Current memories\n\n"
            "(No memories saved for this project yet. Use `memory_write` "
            "to save the first one when you learn something worth keeping.)"
        )
    return (
        f"{_MEMORY_GUIDE}\n\n"
        f"## Current memories\n\n"
        f"_{_MEMORY_DRIFT_CAVEAT}_\n\n"
        f"{memory_context}"
    )


def _skill_layer(skills: list[SkillDefinition] | None = None) -> str | None:
    """Return skill content for the system prompt.

    - always=True skills: full content injected.
    - always=False skills: XML summary for LLM discovery via SkillTool.
    """
    if not skills:
        return None

    parts: list[str] = []

    # Always-on skills: inject full content
    always_skills = [s for s in skills if s.always]
    if always_skills:
        parts.append("# Always-On Skills")
        for s in always_skills:
            parts.append(s.content)

    # On-demand skills: XML summary
    on_demand = [s for s in skills if not s.always]
    if on_demand:
        lines = ["# Available Skills", "<skills>"]
        for s in on_demand:
            lines.append(f'  <skill name="{s.name}">')
            if s.description:
                lines.append(f"    <description>{s.description}</description>")
            if s.when_to_use:
                lines.append(f"    <when-to-use>{s.when_to_use}</when-to-use>")
            if s.arguments:
                lines.append(f"    <arguments>{s.arguments}</arguments>")
            lines.append("  </skill>")
        lines.append("</skills>")
        lines.append("")
        lines.append('Use the `skill` tool to invoke a skill when it matches your current task.')
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else None
