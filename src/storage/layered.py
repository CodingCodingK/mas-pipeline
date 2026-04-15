"""Two-layer file storage for agents and pipelines.

Global layer: `agents/*.md`, `pipelines/*.yaml` at repo root.
Project layer: `projects/<project_id>/{agents,pipelines}/*.{md,yaml}`.

`resolve_*_file(name, project_id)` returns the effective path (project layer
wins). Project layer uses strict names only; the global pipeline layer retains
a legacy `<name>_generation.yaml` fallback for backward compatibility with
`src.api.runs._pipeline_yaml_path`.

Agent deletion at the global layer performs a reference scan over pipeline
YAML files — any static `nodes[].role == <name>` reference in a pipeline that
is not shielded by a project-layer override blocks the deletion.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Module-level root — overridable by tests via monkey-patch.
# Resolves to the repo root (three levels up from this file).
_ROOT: Path = Path(__file__).resolve().parent.parent.parent


class StorageError(Exception):
    """Base class for storage-layer errors."""


class InvalidNameError(StorageError, ValueError):
    """Name failed the [A-Za-z0-9_-]+ validation rule."""


class AgentInUseError(StorageError):
    """Global agent deletion blocked by static pipeline references."""

    def __init__(self, name: str, references: list[dict]) -> None:
        self.name = name
        self.references = references
        super().__init__(
            f"agent {name!r} is referenced by {len(references)} pipeline(s)"
        )


class AgentProtectedError(StorageError):
    """Write/delete blocked because the agent is marked readonly or hidden."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"agent {name!r} is protected ({reason})")


def _safe_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidNameError(
            f"invalid name {name!r}: must match [A-Za-z0-9_-]+"
        )


def _global_dir(kind: str) -> Path:
    return _ROOT / kind


def _project_dir(kind: str, project_id: int) -> Path:
    return _ROOT / "projects" / str(project_id) / kind


# ── Agent resolver + CRUD ──────────────────────────────────


def resolve_agent_file(name: str, project_id: int | None) -> Path:
    _safe_name(name)
    filename = f"{name}.md"
    if project_id is not None:
        p = _project_dir("agents", project_id) / filename
        if p.is_file():
            return p
    g = _global_dir("agents") / filename
    if g.is_file():
        return g
    raise FileNotFoundError(
        f"agent {name!r} not found (project_id={project_id})"
    )


def read_agent(name: str, project_id: int | None) -> str:
    return resolve_agent_file(name, project_id).read_text(encoding="utf-8")


def _parse_agent_frontmatter(path: Path) -> dict:
    """Extract description, model_tier, tools, hidden, readonly from frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = yaml.safe_load(parts[1]) or {}
    return {
        "description": fm.get("description", ""),
        "model_tier": fm.get("model_tier", ""),
        "tools": fm.get("tools") or [],
        "hidden": bool(fm.get("hidden", False)),
        "readonly": bool(fm.get("readonly", False)),
        "entry_only": bool(fm.get("entry_only", False)),
    }


def is_entry_only_agent(name: str, project_id: int | None) -> bool:
    """Return True if the effective agent file declares `entry_only: true`.

    Entry-only agents are top-level roles (driven by a user conversation or a
    bus adapter) and must never be launched as sub-agents via spawn_agent.
    Missing file / malformed frontmatter / invalid name all return False so a
    broken agent definition cannot masquerade as protected.
    """
    try:
        path = resolve_agent_file(name, project_id)
    except (FileNotFoundError, InvalidNameError):
        return False
    return bool(_parse_agent_frontmatter(path).get("entry_only"))


def _agent_protection(name: str, project_id: int | None) -> tuple[bool, bool]:
    """Return (hidden, readonly) flags for the effective agent file.

    Checks project layer first then global. Missing file → (False, False).
    """
    try:
        path = resolve_agent_file(name, project_id)
    except FileNotFoundError:
        return (False, False)
    meta = _parse_agent_frontmatter(path)
    return (bool(meta.get("hidden")), bool(meta.get("readonly")))


def _list_stems(directory: Path, suffix: str) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob(f"*{suffix}") if p.is_file())


def list_agents_global() -> list[str]:
    return _list_stems(_global_dir("agents"), ".md")


def list_agents_project(project_id: int) -> list[str]:
    return _list_stems(_project_dir("agents", project_id), ".md")


def _check_not_protected(name: str, path: Path) -> None:
    """Raise AgentProtectedError if existing file is hidden or readonly.

    Check the file currently on disk — not the incoming content — so a
    client cannot unlock itself by stripping the frontmatter flag.
    """
    if not path.is_file():
        return
    meta = _parse_agent_frontmatter(path)
    if meta.get("hidden"):
        raise AgentProtectedError(name, "hidden")
    if meta.get("readonly"):
        raise AgentProtectedError(name, "readonly")


def write_agent_global(name: str, content: str) -> bool:
    _safe_name(name)
    d = _global_dir("agents")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.md"
    _check_not_protected(name, path)
    created = not path.is_file()
    path.write_text(content, encoding="utf-8")
    return created


def write_agent_project(name: str, project_id: int, content: str) -> bool:
    _safe_name(name)
    # Project override is also blocked if the effective (global) agent is
    # hidden/readonly — users shouldn't be able to shadow a protected one.
    global_path = _global_dir("agents") / f"{name}.md"
    _check_not_protected(name, global_path)
    d = _project_dir("agents", project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.md"
    _check_not_protected(name, path)
    created = not path.is_file()
    path.write_text(content, encoding="utf-8")
    return created


def delete_agent_global(name: str) -> None:
    _safe_name(name)
    path = _global_dir("agents") / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"agent {name!r} not found in global layer")
    _check_not_protected(name, path)
    refs = find_agent_references_global(name)
    if refs:
        raise AgentInUseError(name, refs)
    path.unlink()


def delete_agent_project(name: str, project_id: int) -> None:
    _safe_name(name)
    path = _project_dir("agents", project_id) / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"agent {name!r} not found in project {project_id}"
        )
    _check_not_protected(name, path)
    path.unlink()


# System-level agents that are always shown in a project's agent list,
# regardless of whether any pipeline references them. These are the chat/
# autonomous-mode entry points and are conceptually "part of the project"
# even when no pipeline calls them.
_PROJECT_PINNED_AGENTS = frozenset({"assistant", "coordinator"})


def _roles_for_pipeline(pipeline_name: str | None, project_id: int) -> set[str]:
    """Roles statically referenced by a single pipeline yaml.

    A Project row binds to exactly one pipeline via `Project.pipeline`. This
    helper resolves that name through the project→global fallback chain and
    returns the role set. Returns empty on missing / malformed / unresolved
    pipeline so a broken binding never breaks the agents list.
    """
    if not pipeline_name:
        return set()
    try:
        path = resolve_pipeline_file(pipeline_name, project_id)
    except FileNotFoundError:
        return set()
    return _extract_roles_from_pipeline(path)


def merged_agents_view(
    project_id: int, pipeline_name: str | None = None
) -> list[dict]:
    g = set(list_agents_global())
    p = set(list_agents_project(project_id))
    pipeline_roles = _roles_for_pipeline(pipeline_name, project_id)
    out: list[dict] = []
    for n in sorted(g | p):
        if n in p and n in g:
            src = "project-override"
        elif n in p:
            src = "project-only"
        else:
            src = "global"
        # Scope filter: show pinned system agents, any agent with a project-
        # local file, and global agents referenced by this project's pipelines.
        # Everything else (global-only agents this project never touches) is
        # hidden to keep the list focused.
        if (
            n not in _PROJECT_PINNED_AGENTS
            and n not in p
            and n not in pipeline_roles
        ):
            continue
        try:
            path = resolve_agent_file(n, project_id)
            meta = _parse_agent_frontmatter(path)
        except FileNotFoundError:
            meta = {}
        if meta.get("hidden"):
            continue
        out.append({"name": n, "source": src, **meta})
    return out


def global_agents_view() -> list[dict]:
    """List global agents with full metadata, filtered for hidden."""
    out: list[dict] = []
    for n in list_agents_global():
        path = _global_dir("agents") / f"{n}.md"
        meta = _parse_agent_frontmatter(path) if path.is_file() else {}
        if meta.get("hidden"):
            continue
        out.append({"name": n, "source": "global", **meta})
    return out


# ── Pipeline resolver + CRUD ───────────────────────────────


def resolve_pipeline_file(name: str, project_id: int | None) -> Path:
    _safe_name(name)
    filename = f"{name}.yaml"
    if project_id is not None:
        p = _project_dir("pipelines", project_id) / filename
        if p.is_file():
            return p
    g = _global_dir("pipelines") / filename
    if g.is_file():
        return g
    g_legacy = _global_dir("pipelines") / f"{name}_generation.yaml"
    if g_legacy.is_file():
        return g_legacy
    raise FileNotFoundError(
        f"pipeline {name!r} not found (project_id={project_id})"
    )


def read_pipeline(name: str, project_id: int | None) -> str:
    return resolve_pipeline_file(name, project_id).read_text(encoding="utf-8")


def list_pipelines_global() -> list[str]:
    return _list_stems(_global_dir("pipelines"), ".yaml")


def list_pipelines_project(project_id: int) -> list[str]:
    return _list_stems(_project_dir("pipelines", project_id), ".yaml")


def write_pipeline_global(name: str, content: str) -> bool:
    _safe_name(name)
    d = _global_dir("pipelines")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.yaml"
    created = not path.is_file()
    path.write_text(content, encoding="utf-8")
    return created


def write_pipeline_project(name: str, project_id: int, content: str) -> bool:
    _safe_name(name)
    d = _project_dir("pipelines", project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.yaml"
    created = not path.is_file()
    path.write_text(content, encoding="utf-8")
    return created


def delete_pipeline_global(name: str) -> None:
    _safe_name(name)
    path = _global_dir("pipelines") / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"pipeline {name!r} not found in global layer")
    path.unlink()


def delete_pipeline_project(name: str, project_id: int) -> None:
    _safe_name(name)
    path = _project_dir("pipelines", project_id) / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"pipeline {name!r} not found in project {project_id}"
        )
    path.unlink()


def merged_pipelines_view(project_id: int) -> list[dict]:
    g = set(list_pipelines_global())
    p = set(list_pipelines_project(project_id))
    out: list[dict] = []
    for n in sorted(g | p):
        if n in p and n in g:
            src = "project-override"
        elif n in p:
            src = "project-only"
        else:
            src = "global"
        out.append({"name": n, "source": src})
    return out


# ── Reference scanner ──────────────────────────────────────


def _extract_roles_from_pipeline(pipe_path: Path) -> set[str]:
    """Parse a pipeline YAML and return the set of role names in nodes[].

    Tolerates malformed YAML / non-dict structure / missing nodes by returning
    an empty set. A broken pipeline contributes zero references and should
    not block unrelated operations."""
    try:
        text = pipe_path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception as exc:
        logger.warning("failed to parse pipeline yaml %s: %s", pipe_path, exc)
        return set()
    if not isinstance(data, dict):
        return set()
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return set()
    roles: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        r = node.get("role")
        if isinstance(r, str):
            roles.add(r)
    return roles


def _iter_project_dirs() -> Iterable[tuple[int, Path]]:
    """Yield (project_id, project_dir) for numeric subdirs of `projects/`.
    Non-numeric subdirectory names are skipped silently."""
    projects_root = _ROOT / "projects"
    if not projects_root.is_dir():
        return
    for entry in projects_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        yield pid, entry


def find_agent_references_global(agent_name: str) -> list[dict]:
    """Scan pipeline YAML files for static references to a global agent.

    Only references that would actually resolve to the *global* file count —
    a project with its own `projects/<id>/agents/<name>.md` override is
    unaffected by global deletion and is skipped."""
    refs: list[dict] = []

    # 1. Global pipelines always reference the global agent (no override possible).
    global_pipelines_dir = _global_dir("pipelines")
    if global_pipelines_dir.is_dir():
        for pipe_path in sorted(global_pipelines_dir.glob("*.yaml")):
            if agent_name in _extract_roles_from_pipeline(pipe_path):
                refs.append(
                    {
                        "project_id": None,
                        "pipeline": pipe_path.stem,
                        "role": agent_name,
                    }
                )

    # 2. Per-project pipelines, minus projects that override the agent.
    for pid, proj_dir in _iter_project_dirs():
        if (proj_dir / "agents" / f"{agent_name}.md").is_file():
            continue  # project has its own copy — unaffected
        pipelines_dir = proj_dir / "pipelines"
        if not pipelines_dir.is_dir():
            continue
        for pipe_path in sorted(pipelines_dir.glob("*.yaml")):
            if agent_name in _extract_roles_from_pipeline(pipe_path):
                refs.append(
                    {
                        "project_id": pid,
                        "pipeline": pipe_path.stem,
                        "role": agent_name,
                    }
                )

    return refs
