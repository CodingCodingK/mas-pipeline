"""Integration tests for skill system — factory integration, SkillTool registration."""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


# --- create_agent with skills whitelist ---

print("=== create_agent with skills whitelist ===")


async def test_agent_with_skills():
    """Agent with skills: [summarize] should have SkillTool registered."""
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "skills: [summarize]\n"
        "---\n"
        "\n"
        "You are a summarizer agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "summarizer.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        # Mock _AGENTS_DIR to use tmp
        with patch("src.agent.factory._AGENTS_DIR", role_path.parent):
            # Mock route to return a dummy adapter
            mock_adapter = MagicMock()
            with patch("src.agent.factory.route", return_value=mock_adapter):
                from src.agent.factory import create_agent

                state = await create_agent(
                    role="summarizer",
                    task_description="Summarize this doc",
                    permission_mode=PermissionMode.BYPASS,
                )

                # Check SkillTool is registered (summarize is on-demand by default)
                tool_names = list(state.tools._tools.keys())
                check("read_file registered", "read_file" in tool_names)
                check("skill tool registered", "skill" in tool_names)

                # Check system prompt contains skill info
                sys_msg = state.messages[0]["content"]
                check("system prompt has Available Skills", "# Available Skills" in sys_msg or "summarize" in sys_msg.lower())


asyncio.run(test_agent_with_skills())

# --- create_agent without skills ---

print("\n=== create_agent without skills ===")


async def test_agent_no_skills():
    """Agent without skills field should not have SkillTool."""
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "---\n"
        "\n"
        "You are a reader agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "reader.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        with patch("src.agent.factory._AGENTS_DIR", role_path.parent):
            mock_adapter = MagicMock()
            with patch("src.agent.factory.route", return_value=mock_adapter):
                from src.agent.factory import create_agent

                state = await create_agent(
                    role="reader",
                    task_description="Read files",
                    permission_mode=PermissionMode.BYPASS,
                )

                tool_names = list(state.tools._tools.keys())
                check("read_file registered", "read_file" in tool_names)
                check("no skill tool", "skill" not in tool_names)

                sys_msg = state.messages[0]["content"]
                check("no skills in prompt", "# Available Skills" not in sys_msg)
                check("no always-on in prompt", "# Always-On Skills" not in sys_msg)


asyncio.run(test_agent_no_skills())

# --- SkillTool registered only when on-demand skills exist ---

print("\n=== SkillTool registration: only for on-demand ===")


async def test_only_always_skills():
    """Agent with only always=True skills should not get SkillTool."""
    from src.permissions.types import PermissionMode

    # Create an always-on skill
    always_skill_content = (
        "---\n"
        "name: style-guide\n"
        "always: true\n"
        "---\n"
        "\n"
        "Always use snake_case.\n"
    )

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "skills: [style-guide]\n"
        "---\n"
        "\n"
        "You are a coder.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        # Create skill file
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()
        (skills_dir / "style-guide.md").write_text(always_skill_content, encoding="utf-8")

        # Create role file
        agents_dir = Path(tmp) / "agents"
        agents_dir.mkdir()
        (agents_dir / "coder.md").write_text(role_content, encoding="utf-8")

        with (
            patch("src.agent.factory._AGENTS_DIR", agents_dir),
            patch("src.skills.loader._SKILLS_DIR", skills_dir),
        ):
            mock_adapter = MagicMock()
            with patch("src.agent.factory.route", return_value=mock_adapter):
                from src.agent.factory import create_agent

                state = await create_agent(
                    role="coder",
                    task_description="Write code",
                    permission_mode=PermissionMode.BYPASS,
                )

                tool_names = list(state.tools._tools.keys())
                check("no skill tool for always-only", "skill" not in tool_names)

                sys_msg = state.messages[0]["content"]
                check("always skill in prompt", "Always use snake_case." in sys_msg)


asyncio.run(test_only_always_skills())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
