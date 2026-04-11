"""REST endpoint for downloading a completed run's final output as markdown."""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.api.auth import require_api_key
from src.export import (
    ExportArtifact,
    NoFinalOutputError,
    RunNotFinishedError,
    RunNotFoundError,
    export_markdown,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


def _content_disposition(ascii_name: str, display_name: str) -> str:
    """Build an RFC 6266 Content-Disposition header with both ASCII fallback
    and UTF-8 extended form, so legacy and modern browsers both get a
    sensible filename when the pipeline name contains non-ASCII characters.

    `ascii_name` is the already-sanitized filename ([A-Za-z0-9_-]+.md).
    `display_name` is the original name with non-ASCII characters preserved,
    which is percent-encoded for the `filename*` extended form.
    """
    encoded = quote(display_name, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded}"
    )


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str) -> Response:
    try:
        artifact: ExportArtifact = await export_markdown(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except RunNotFinishedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NoFinalOutputError:
        raise HTTPException(
            status_code=404,
            detail="run completed but has no exportable output",
        )

    return Response(
        content=artifact.content.encode("utf-8"),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": _content_disposition(
                artifact.filename, artifact.display_filename
            )
        },
    )
