"""Export business layer: extract a completed run's final_output as a downloadable artifact."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.engine.run import get_run


class ExportError(Exception):
    """Base class for all exporter-specific errors."""


class RunNotFoundError(ExportError):
    """The requested run_id does not exist."""


class RunNotFinishedError(ExportError):
    """The run exists but is not in 'completed' state."""


class NoFinalOutputError(ExportError):
    """The run is completed but its final_output is missing or empty."""


@dataclass(frozen=True)
class ExportArtifact:
    filename: str
    content: str
    content_type: str
    display_filename: str


_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_filename_part(name: str) -> str:
    """Replace characters outside [A-Za-z0-9_-] with underscores.

    Non-ASCII is also collapsed to `_` — the regex character class is ASCII-only.
    """
    return _FILENAME_UNSAFE.sub("_", name)


async def export_markdown(run_id: str) -> ExportArtifact:
    """Extract a completed run's final_output and return it as an ExportArtifact.

    Raises:
        RunNotFoundError: run_id does not exist
        RunNotFinishedError: run.status != 'completed'
        NoFinalOutputError: run is completed but final_output is missing or empty
    """
    run = await get_run(run_id)
    if run is None:
        raise RunNotFoundError(f"run '{run_id}' not found")

    if run.status != "completed":
        raise RunNotFinishedError(
            f"run '{run_id}' is not exportable: current status is '{run.status}'"
        )

    metadata = run.metadata_ or {}
    final_output = metadata.get("final_output")
    if not final_output:
        raise NoFinalOutputError(
            f"run '{run_id}' is completed but has no final_output in metadata"
        )

    pipeline_name = run.pipeline or "run"
    sanitized = _sanitize_filename_part(pipeline_name)
    run_id_short = (run.run_id or "")[:8]
    filename = f"{sanitized}_{run_id_short}.md"
    display_filename = f"{pipeline_name}_{run_id_short}.md"

    return ExportArtifact(
        filename=filename,
        content=final_output,
        content_type="text/markdown; charset=utf-8",
        display_filename=display_filename,
    )
