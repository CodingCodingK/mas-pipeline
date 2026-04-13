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
    """
    prompt = system_prompt
    if runtime_context:
        ctx_lines = "\n".join(f"- {k}: {v}" for k, v in runtime_context.items())
        prompt += f"\n\n# Runtime Context\n{ctx_lines}"

    return [
        {"role": "system", "content": prompt},
        *history,
        {"role": "user", "content": user_input},
    ]


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


def _memory_layer(memory_context: str | None = None) -> str | None:
    """Return relevant memories for this agent/project."""
    if memory_context:
        return f"# Memory\n{_MEMORY_DRIFT_CAVEAT}\n\n{memory_context}"
    return None


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
