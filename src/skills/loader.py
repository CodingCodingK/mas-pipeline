"""Skill loader: scan skills/*.md, parse frontmatter + body into SkillDefinition."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.skills.types import SkillDefinition

logger = logging.getLogger(__name__)

# Default skills directory relative to project root
_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


def load_skill(path: Path) -> SkillDefinition:
    """Parse a single skill .md file into a SkillDefinition.

    Raises FileNotFoundError if path does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Skill file not found: {path}")

    text = path.read_text(encoding="utf-8")
    metadata, body = _parse_frontmatter(text)

    return SkillDefinition(
        name=metadata.get("name", path.stem),
        content=body,
        description=metadata.get("description", ""),
        when_to_use=metadata.get("when_to_use", ""),
        context=metadata.get("context", "inline"),
        model_tier=metadata.get("model_tier", "inherit"),
        tools=metadata.get("tools", []),
        always=metadata.get("always", False),
        arguments=metadata.get("arguments", ""),
    )


def load_skills(skills_dir: Path | None = None) -> dict[str, SkillDefinition]:
    """Scan a directory for all .md skill files.

    Returns dict keyed by skill name. Returns empty dict if directory
    does not exist or contains no .md files.
    """
    directory = skills_dir or _SKILLS_DIR
    if not directory.is_dir():
        return {}

    skills: dict[str, SkillDefinition] = {}
    for md_file in sorted(directory.glob("*.md")):
        try:
            skill = load_skill(md_file)
            skills[skill.name] = skill
        except Exception:
            logger.warning("Failed to load skill %s", md_file, exc_info=True)

    return skills


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns (metadata, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1])
            return (fm or {}), parts[2].strip()
    return {}, text.strip()
