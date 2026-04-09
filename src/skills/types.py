"""Skill types: definition and execution result."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillDefinition:
    """A parsed skill from a skills/*.md file."""

    name: str
    content: str                        # Prompt template body
    description: str = ""
    when_to_use: str = ""
    context: str = "inline"             # "inline" | "fork"
    model_tier: str = "inherit"         # Fork sub-agent model tier
    tools: list[str] = field(default_factory=list)  # Fork sub-agent tools
    always: bool = False                # True = inject full content into system prompt
    arguments: str = ""                 # Argument hint (e.g. "topic")


@dataclass
class SkillResult:
    """Outcome of a skill execution."""

    mode: str               # "inline" | "fork"
    output: str
    skill_name: str
    success: bool = True
