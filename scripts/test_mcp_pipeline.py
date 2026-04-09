"""Integration tests for pipeline MCP lifecycle."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


print("=== Pipeline: MCPManager lifecycle ===")


async def test_pipeline_mcp_lifecycle():
    """Verify MCPManager is started before nodes and shut down after."""
    lifecycle = []

    # Track MCPManager lifecycle
    mock_mgr_instance = MagicMock()

    async def mock_start(configs):
        lifecycle.append("mcp_start")

    async def mock_shutdown():
        lifecycle.append("mcp_shutdown")

    mock_mgr_instance.start = AsyncMock(side_effect=mock_start)
    mock_mgr_instance.shutdown = AsyncMock(side_effect=mock_shutdown)
    mock_mgr_instance.get_tools = MagicMock(return_value=[])

    mock_mgr_cls = MagicMock(return_value=mock_mgr_instance)

    # Mock settings with mcp_servers
    mock_settings = MagicMock()
    mock_settings.mcp_servers = {"github": {"command": "npx", "args": []}}

    # Mock the pipeline loading and run
    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    mock_pipeline = PipelineDefinition(
        name="test",
        description="test pipeline",
        nodes=[NodeDefinition(name="n1", role="general", output="out1")],
        output_to_node={"out1": "n1"},
        dependencies={"n1": set()},
    )

    async def mock_run_node(**kwargs):
        lifecycle.append("node_run")
        return "result"

    with patch("src.mcp.manager.MCPManager", mock_mgr_cls), \
         patch("src.project.config.get_settings", return_value=mock_settings), \
         patch("src.engine.pipeline.load_pipeline", return_value=mock_pipeline), \
         patch("src.engine.run.update_run_status", new_callable=AsyncMock), \
         patch("src.engine.run.finish_run", new_callable=AsyncMock), \
         patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1), \
         patch("src.engine.pipeline._run_node", new_callable=AsyncMock, return_value="output"):

        from src.engine.pipeline import execute_pipeline
        result = await execute_pipeline(
            pipeline_name="test",
            run_id="run-1",
            project_id=1,
            user_input="hello",
        )

        check("mcp_start happened", "mcp_start" in lifecycle)
        check("mcp_shutdown happened", "mcp_shutdown" in lifecycle)
        check("mcp started before shutdown", lifecycle.index("mcp_start") < lifecycle.index("mcp_shutdown"))
        check("pipeline completed", result.status == "completed")


asyncio.run(test_pipeline_mcp_lifecycle())

print("\n=== Pipeline: no MCP servers configured ===")


async def test_pipeline_no_mcp():
    """Pipeline works normally without MCP servers."""
    mock_mgr_instance = MagicMock()
    mock_mgr_instance.start = AsyncMock()
    mock_mgr_instance.shutdown = AsyncMock()

    mock_mgr_cls = MagicMock(return_value=mock_mgr_instance)

    mock_settings = MagicMock()
    mock_settings.mcp_servers = {}  # No MCP servers

    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    mock_pipeline = PipelineDefinition(
        name="test",
        description="test",
        nodes=[NodeDefinition(name="n1", role="general", output="out1")],
        output_to_node={"out1": "n1"},
        dependencies={"n1": set()},
    )

    with patch("src.mcp.manager.MCPManager", mock_mgr_cls), \
         patch("src.project.config.get_settings", return_value=mock_settings), \
         patch("src.engine.pipeline.load_pipeline", return_value=mock_pipeline), \
         patch("src.engine.run.update_run_status", new_callable=AsyncMock), \
         patch("src.engine.run.finish_run", new_callable=AsyncMock), \
         patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1), \
         patch("src.engine.pipeline._run_node", new_callable=AsyncMock, return_value="output"):

        from src.engine.pipeline import execute_pipeline
        result = await execute_pipeline(
            pipeline_name="test",
            run_id="run-2",
            project_id=1,
            user_input="hello",
        )

        check("start not called (no servers)", not mock_mgr_instance.start.called)
        check("shutdown still called", mock_mgr_instance.shutdown.called)
        check("pipeline completed", result.status == "completed")


asyncio.run(test_pipeline_no_mcp())

print("\n=== Pipeline: MCP shutdown on failure ===")


async def test_pipeline_mcp_shutdown_on_failure():
    """MCPManager shuts down even if pipeline fails."""
    mock_mgr_instance = MagicMock()
    mock_mgr_instance.start = AsyncMock()
    mock_mgr_instance.shutdown = AsyncMock()

    mock_mgr_cls = MagicMock(return_value=mock_mgr_instance)

    mock_settings = MagicMock()
    mock_settings.mcp_servers = {"test": {"command": "test"}}

    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    mock_pipeline = PipelineDefinition(
        name="test",
        description="test",
        nodes=[NodeDefinition(name="n1", role="general", output="out1")],
        output_to_node={"out1": "n1"},
        dependencies={"n1": set()},
    )

    with patch("src.mcp.manager.MCPManager", mock_mgr_cls), \
         patch("src.project.config.get_settings", return_value=mock_settings), \
         patch("src.engine.pipeline.load_pipeline", return_value=mock_pipeline), \
         patch("src.engine.run.update_run_status", new_callable=AsyncMock), \
         patch("src.engine.run.finish_run", new_callable=AsyncMock), \
         patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1), \
         patch("src.engine.pipeline._run_node", new_callable=AsyncMock, side_effect=RuntimeError("node failed")):

        from src.engine.pipeline import execute_pipeline
        result = await execute_pipeline(
            pipeline_name="test",
            run_id="run-3",
            project_id=1,
            user_input="hello",
        )

        check("shutdown called despite failure", mock_mgr_instance.shutdown.called)
        check("pipeline status failed", result.status == "failed")


asyncio.run(test_pipeline_mcp_shutdown_on_failure())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
