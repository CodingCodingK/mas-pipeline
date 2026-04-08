"""Context builder: role file parsing, system prompt construction, messages assembly."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import yaml


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
) -> str:
    """Build system prompt by concatenating layers: identity, role, memory, skill.

    Skill layer is Phase 5 placeholder (returns None, skipped).
    """
    layers: list[str | None] = [
        _identity_layer(project_root),
        _role_layer(role_body),
        _memory_layer(memory_context),
        _skill_layer(),
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


def _memory_layer(memory_context: str | None = None) -> str | None:
    """Return relevant memories for this agent/project."""
    if memory_context:
        return f"# Memory\n{memory_context}"
    return None


def _skill_layer() -> str | None:
    """Phase 5: return skill summaries available to this agent."""
    return None
