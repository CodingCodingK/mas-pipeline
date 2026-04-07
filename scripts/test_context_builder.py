"""Verification for context builder: parse_role_file, build_system_prompt, build_messages."""

import os
import sys
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.context import build_messages, build_system_prompt, parse_role_file

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_parse_role_file_with_frontmatter():
    print("=== parse_role_file: with frontmatter ===")
    role_path = os.path.join(PROJECT_ROOT, "agents", "general.md")
    meta, body = parse_role_file(role_path)

    assert meta["description"] == "通用助手", f"Expected '通用助手', got {meta['description']}"
    assert meta["model_tier"] == "medium", f"Expected 'medium', got {meta['model_tier']}"
    assert meta["tools"] == ["read_file", "shell"], f"Expected ['read_file', 'shell'], got {meta['tools']}"
    assert len(body) > 0, "Body should not be empty"
    assert "通用助手" in body, f"Body should mention role: {body[:50]}"
    print(f"  meta: {meta}")
    print(f"  body: {body[:60]}...")
    print("  OK")


def test_parse_role_file_without_frontmatter():
    print("=== parse_role_file: without frontmatter ===")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("You are a plain agent.")
        tmp_path = f.name

    try:
        meta, body = parse_role_file(tmp_path)
        assert meta == {}, f"Expected empty dict, got {meta}"
        assert body == "You are a plain agent.", f"Expected plain text, got {body}"
        print("  OK")
    finally:
        os.unlink(tmp_path)


def test_build_system_prompt():
    print("=== build_system_prompt ===")
    prompt = build_system_prompt("You are a researcher.", PROJECT_ROOT)

    assert "# Environment" in prompt, "Should have identity layer"
    assert "OS:" in prompt, "Should have OS info"
    assert "Python:" in prompt, "Should have Python version"
    assert PROJECT_ROOT in prompt, "Should have project root"
    assert "# Role" in prompt, "Should have role layer"
    assert "You are a researcher." in prompt, "Should have role body"
    print(f"  prompt length: {len(prompt)} chars")
    print("  OK")


def test_build_system_prompt_no_project_root():
    print("=== build_system_prompt: no project root ===")
    prompt = build_system_prompt("Helper agent.", project_root=None)

    assert "Project root" not in prompt, "Should not have project root"
    assert "Helper agent." in prompt, "Should have role body"
    print("  OK")


def test_build_messages_fresh():
    print("=== build_messages: fresh conversation ===")
    msgs = build_messages("You are a helper.", [], "hello")

    assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are a helper."
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "hello"
    print("  OK")


def test_build_messages_with_history():
    print("=== build_messages: with history ===")
    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]
    msgs = build_messages("sys prompt", history, "second question")

    assert len(msgs) == 4, f"Expected 4 messages, got {len(msgs)}"
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "first question"
    assert msgs[2]["role"] == "assistant"
    assert msgs[3]["role"] == "user"
    assert msgs[3]["content"] == "second question"
    print("  OK")


def test_build_messages_with_runtime_context():
    print("=== build_messages: with runtime_context ===")
    ctx = {"current_time": "2026-04-07 15:00", "agent_id": "agent-1"}
    msgs = build_messages("You are a helper.", [], "hi", runtime_context=ctx)

    content = msgs[0]["content"]
    assert "# Runtime Context" in content, "Should have runtime context section"
    assert "current_time: 2026-04-07 15:00" in content
    assert "agent_id: agent-1" in content
    print("  OK")


def test_build_messages_no_runtime_context():
    print("=== build_messages: no runtime_context ===")
    msgs = build_messages("You are a helper.", [], "hi", runtime_context=None)

    assert "Runtime Context" not in msgs[0]["content"]
    print("  OK")


def main():
    print("\n--- Context Builder Verification ---\n")

    test_parse_role_file_with_frontmatter()
    test_parse_role_file_without_frontmatter()
    test_build_system_prompt()
    test_build_system_prompt_no_project_root()
    test_build_messages_fresh()
    test_build_messages_with_history()
    test_build_messages_with_runtime_context()
    test_build_messages_no_runtime_context()

    print("\n[PASS] All context builder tests passed!\n")


if __name__ == "__main__":
    main()
