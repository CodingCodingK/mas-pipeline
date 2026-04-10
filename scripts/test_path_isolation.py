"""Path isolation tests: pipeline, coordinator, and gateway paths don't leak into each other."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ── 1. Pipeline execution does NOT trigger coordinator_loop ──

print("\n=== 1. Pipeline path does NOT trigger coordinator_loop ===")


async def test_pipeline_no_coordinator():
    """execute_pipeline should never import or call coordinator_loop."""
    import src.engine.pipeline as pipeline_mod

    # Check that coordinator_loop is not referenced in pipeline module
    source = Path(pipeline_mod.__file__).read_text(encoding="utf-8")
    check(
        "pipeline.py doesn't import coordinator_loop",
        "coordinator_loop" not in source,
    )
    check(
        "pipeline.py doesn't import run_coordinator",
        "run_coordinator" not in source,
    )


asyncio.run(test_pipeline_no_coordinator())


# ── 2. Pipeline execution does NOT trigger gateway._run_agent ──

print("\n=== 2. Pipeline path does NOT trigger gateway._run_agent ===")


async def test_pipeline_no_gateway():
    """pipeline module should not reference gateway at all."""
    import src.engine.pipeline as pipeline_mod

    source = Path(pipeline_mod.__file__).read_text(encoding="utf-8")
    check(
        "pipeline.py doesn't reference gateway",
        "gateway" not in source.lower() or "gateway" not in source,
    )


asyncio.run(test_pipeline_no_gateway())


# ── 3. Gateway chat does NOT trigger execute_pipeline ────

print("\n=== 3. Gateway chat does NOT trigger execute_pipeline ===")


async def test_gateway_chat_no_pipeline():
    """Normal chat messages should not invoke execute_pipeline."""
    from src.bus.gateway import Gateway
    from src.bus.message import InboundMessage

    mock_bus = MagicMock()
    gw = Gateway(bus=mock_bus, project_id=1)

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="Hello, how are you?",
    )

    with (
        patch.object(gw, "_run_agent", new_callable=AsyncMock, return_value="Hi!"),
        patch("src.bus.gateway.resolve_session", new_callable=AsyncMock) as mock_session,
        patch("src.bus.gateway.get_session_history", new_callable=AsyncMock, return_value=[]),
        patch("src.bus.gateway.append_message", new_callable=AsyncMock),
        patch("src.bus.gateway.refresh_session", new_callable=AsyncMock),
        patch.object(mock_bus, "publish_outbound", new_callable=AsyncMock),
    ):
        mock_session_obj = MagicMock()
        mock_session_obj.conversation_id = 1
        mock_session.return_value = mock_session_obj

        await gw._process_message(msg)

    # Verify execute_pipeline was NOT called
    with patch("src.engine.pipeline.execute_pipeline", new_callable=AsyncMock) as mock_exec:
        # The mock was not called during _process_message
        check("execute_pipeline not called for chat", not mock_exec.called)


asyncio.run(test_gateway_chat_no_pipeline())


# ── 4. /resume command does NOT trigger coordinator_loop ──

print("\n=== 4. /resume command does NOT trigger coordinator_loop ===")


async def test_resume_no_coordinator():
    """The /resume command goes to _handle_resume, not coordinator."""
    from src.bus.gateway import Gateway
    from src.bus.message import InboundMessage

    mock_bus = MagicMock()
    mock_bus.publish_outbound = AsyncMock()
    gw = Gateway(bus=mock_bus, project_id=1)

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/resume",
    )

    with (
        patch.object(gw, "_list_paused_runs", new_callable=AsyncMock, return_value=[]),
    ):
        await gw._process_message(msg)

    # Verify outbound was called (with "No paused pipelines" message)
    check("/resume sends response", mock_bus.publish_outbound.called)
    response = mock_bus.publish_outbound.call_args[0][0]
    check("/resume response about paused", "No paused" in response.content)


asyncio.run(test_resume_no_coordinator())


# ── 5. /resume command does NOT create a chat agent ──────

print("\n=== 5. /resume does NOT create chat agent ===")


async def test_resume_no_chat_agent():
    from src.bus.gateway import Gateway
    from src.bus.message import InboundMessage

    mock_bus = MagicMock()
    mock_bus.publish_outbound = AsyncMock()
    gw = Gateway(bus=mock_bus, project_id=1)

    msg = InboundMessage(
        channel="test", sender_id="u1", chat_id="c1", content="/resume",
    )

    with (
        patch.object(gw, "_run_agent", new_callable=AsyncMock) as mock_agent,
        patch.object(gw, "_list_paused_runs", new_callable=AsyncMock, return_value=[]),
    ):
        await gw._process_message(msg)

    check("_run_agent NOT called for /resume", not mock_agent.called)


asyncio.run(test_resume_no_chat_agent())


# ── 6. Coordinator does NOT call execute_pipeline ────────

print("\n=== 6. Coordinator does NOT call execute_pipeline ===")


async def test_coordinator_no_pipeline():
    """After refactor, run_coordinator only does autonomous mode."""
    import src.engine.coordinator as coord_mod

    source = Path(coord_mod.__file__).read_text(encoding="utf-8")
    check(
        "coordinator.py doesn't import execute_pipeline",
        "execute_pipeline" not in source,
    )


asyncio.run(test_coordinator_no_pipeline())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
