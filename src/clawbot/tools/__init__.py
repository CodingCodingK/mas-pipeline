"""ClawBot tool instances. Registered into the global tool dict by
`src.tools.builtins.get_all_tools`, then pulled by role file whitelist."""

from __future__ import annotations

from src.clawbot.tools.cancel_pending_run import CancelPendingRunTool
from src.clawbot.tools.cancel_run import CancelRunTool
from src.clawbot.tools.confirm_pending_run import ConfirmPendingRunTool
from src.clawbot.tools.get_project_info import GetProjectInfoTool
from src.clawbot.tools.get_run_progress import GetRunProgressTool
from src.clawbot.tools.list_projects import ListProjectsTool
from src.clawbot.tools.persona_edit import PersonaEditTool
from src.clawbot.tools.persona_write import PersonaWriteTool
from src.clawbot.tools.resume_run import ResumeRunTool
from src.clawbot.tools.search_project_docs import SearchProjectDocsTool
from src.clawbot.tools.start_project_run import StartProjectRunTool


def get_clawbot_tools() -> list:
    return [
        ListProjectsTool(),
        GetProjectInfoTool(),
        SearchProjectDocsTool(),
        StartProjectRunTool(),
        ConfirmPendingRunTool(),
        CancelPendingRunTool(),
        CancelRunTool(),
        GetRunProgressTool(),
        PersonaWriteTool(),
        PersonaEditTool(),
        ResumeRunTool(),
    ]


__all__ = [
    "ListProjectsTool",
    "GetProjectInfoTool",
    "SearchProjectDocsTool",
    "StartProjectRunTool",
    "ConfirmPendingRunTool",
    "CancelPendingRunTool",
    "CancelRunTool",
    "GetRunProgressTool",
    "PersonaWriteTool",
    "PersonaEditTool",
    "ResumeRunTool",
    "get_clawbot_tools",
]
