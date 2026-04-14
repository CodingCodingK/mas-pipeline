"""ClawBot — third-party chat (Discord/QQ/WeChat) top-level agent.

Lives in its own module so that nothing outside src/clawbot/ depends on
clawbot internals. The single integration point is
`SessionRunner._build_agent_state` dispatching on `role == "clawbot"`.
"""

from src.clawbot.factory import create_clawbot_agent
from src.clawbot.progress_reporter import ChatProgressReporter
from src.clawbot.session_state import ClawbotSession, PendingRun, get_pending_store

__all__ = [
    "create_clawbot_agent",
    "ChatProgressReporter",
    "ClawbotSession",
    "PendingRun",
    "get_pending_store",
]
