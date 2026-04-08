"""Anthropic adapter tests: request construction, response parsing, router integration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.anthropic import AnthropicAdapter
from src.llm.adapter import LLMResponse, ToolCallRequest, Usage

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


# Create adapter instance for testing (no real API calls)
adapter = AnthropicAdapter(
    api_base="https://api.anthropic.com",
    api_key="test-key",
    model="claude-sonnet-4-6",
)

# ── 1. Request construction ─────────────────────────────

print("\n=== 1. System message extraction ===")

req = adapter._build_request([
    {"role": "system", "content": "You are a helper."},
    {"role": "user", "content": "Hello"},
])
check("system extracted", req.get("system") == "You are a helper.")
check("system not in messages", all(m["role"] != "system" for m in req["messages"]))
check("user message preserved", req["messages"][0]["role"] == "user")
check("model set", req["model"] == "claude-sonnet-4-6")
check("max_tokens default", req["max_tokens"] == 4096)

print("\n=== 2. Text-only messages ===")

req = adapter._build_request([
    {"role": "user", "content": "What is 2+2?"},
])
check("no system param", "system" not in req)
check("one message", len(req["messages"]) == 1)
check("user content is string", req["messages"][0]["content"] == "What is 2+2?")

print("\n=== 3. Tool calls conversion ===")

req = adapter._build_request([
    {"role": "user", "content": "Read the file"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "tc_1", "function": {"name": "read_file", "arguments": {"file_path": "/tmp/x.py"}}}
    ]},
    {"role": "tool", "tool_call_id": "tc_1", "content": "file contents here"},
])
msgs = req["messages"]
check("3 roles converted", len(msgs) >= 2)  # user + assistant + tool_result (merged into user)

# Check assistant message has tool_use block
asst = msgs[1]
check("assistant role", asst["role"] == "assistant")
check("assistant has content blocks", isinstance(asst["content"], list))
tool_use_block = asst["content"][0]
check("tool_use type", tool_use_block["type"] == "tool_use")
check("tool_use id", tool_use_block["id"] == "tc_1")
check("tool_use name", tool_use_block["name"] == "read_file")
check("tool_use input", tool_use_block["input"] == {"file_path": "/tmp/x.py"})

# Check tool result converted to user message with tool_result block
# After merge, the tool_result should be in a user message
tool_result_msg = msgs[2]
check("tool_result is user role", tool_result_msg["role"] == "user")
tool_result_content = tool_result_msg["content"]
if isinstance(tool_result_content, list):
    tr_block = tool_result_content[0]
    check("tool_result type", tr_block["type"] == "tool_result")
    check("tool_result tool_use_id", tr_block["tool_use_id"] == "tc_1")
    check("tool_result content", tr_block["content"] == "file contents here")
else:
    check("tool_result is list", False, f"got {type(tool_result_content)}")

print("\n=== 4. Multimodal conversion ===")

req = adapter._build_request([
    {"role": "user", "content": [
        {"type": "text", "text": "Describe this image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo"}},
    ]},
])
content = req["messages"][0]["content"]
check("multimodal is list", isinstance(content, list))
check("first block is text", content[0] == {"type": "text", "text": "Describe this image"})
img_block = content[1]
check("image type", img_block["type"] == "image")
check("image source type", img_block["source"]["type"] == "base64")
check("image media_type", img_block["source"]["media_type"] == "image/png")
check("image data", img_block["source"]["data"] == "iVBORw0KGgo")

print("\n=== 5. Adjacent same-role merging ===")

req = adapter._build_request([
    {"role": "user", "content": "First message"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "tc_1", "function": {"name": "shell", "arguments": {"command": "ls"}}},
        {"id": "tc_2", "function": {"name": "read_file", "arguments": {"file_path": "/tmp/x"}}},
    ]},
    {"role": "tool", "tool_call_id": "tc_1", "content": "file1.py"},
    {"role": "tool", "tool_call_id": "tc_2", "content": "file contents"},
])
msgs = req["messages"]
# Two tool results (both user role) should be merged into one user message
roles = [m["role"] for m in msgs]
check("alternating roles", roles == ["user", "assistant", "user"], f"got {roles}")
merged_user = msgs[2]
check("merged has 2 tool_results", isinstance(merged_user["content"], list) and len(merged_user["content"]) == 2)

print("\n=== 6. Tools format conversion ===")

req = adapter._build_request(
    [{"role": "user", "content": "hi"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }],
)
check("tools present", "tools" in req)
tool = req["tools"][0]
check("tool name", tool["name"] == "read_file")
check("tool description", tool["description"] == "Read a file")
check("tool input_schema", "properties" in tool["input_schema"])

# ── 7. Response parsing ─────────────────────────────────

print("\n=== 7. Text response parsing ===")

resp = adapter._parse_response({
    "content": [{"type": "text", "text": "Hello world"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
})
check("content", resp.content == "Hello world")
check("no tool_calls", resp.tool_calls == [])
check("finish_reason stop", resp.finish_reason == "stop")
check("input_tokens", resp.usage.input_tokens == 10)
check("output_tokens", resp.usage.output_tokens == 5)
check("no thinking", resp.thinking is None)

print("\n=== 8. Tool use response parsing ===")

resp = adapter._parse_response({
    "content": [
        {"type": "text", "text": "I'll read that file."},
        {"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"file_path": "/tmp/x"}},
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 20, "output_tokens": 15},
})
check("content with tool_use", resp.content == "I'll read that file.")
check("one tool_call", len(resp.tool_calls) == 1)
tc = resp.tool_calls[0]
check("tool_call id", tc.id == "tc_1")
check("tool_call name", tc.name == "read_file")
check("tool_call args", tc.arguments == {"file_path": "/tmp/x"})
check("finish_reason tool_calls", resp.finish_reason == "tool_calls")

print("\n=== 9. Thinking response parsing ===")

resp = adapter._parse_response({
    "content": [
        {"type": "thinking", "thinking": "Let me think about this..."},
        {"type": "text", "text": "The answer is 42."},
    ],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 30, "output_tokens": 25},
})
check("thinking extracted", resp.thinking == "Let me think about this...")
check("content after thinking", resp.content == "The answer is 42.")

print("\n=== 10. Multiple text blocks ===")

resp = adapter._parse_response({
    "content": [
        {"type": "text", "text": "First part."},
        {"type": "text", "text": "Second part."},
    ],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 5, "output_tokens": 10},
})
check("multiple text joined", resp.content == "First part.\nSecond part.")

print("\n=== 11. Stop reason mapping ===")

for stop_reason, expected in [("end_turn", "stop"), ("tool_use", "tool_calls"), ("max_tokens", "stop")]:
    resp = adapter._parse_response({
        "content": [{"type": "text", "text": "x"}],
        "stop_reason": stop_reason,
        "usage": {},
    })
    check(f"stop_reason {stop_reason} → {expected}", resp.finish_reason == expected)

# ── 12. Router ──────────────────────────────────────────

print("\n=== 12. Router integration ===")

from unittest.mock import patch, MagicMock
from src.llm.router import route

mock_settings = MagicMock()
mock_settings.models.strong = "gemini-2.5-pro"
mock_settings.models.medium = "claude-sonnet-4-6"
mock_settings.models.light = "gpt-4o-mini"
mock_settings.providers = {
    "anthropic": MagicMock(api_base="https://api.anthropic.com", api_key="test"),
    "openai": MagicMock(api_base="https://api.openai.com/v1", api_key="test"),
    "gemini": MagicMock(api_base="https://generativelanguage.googleapis.com/v1beta/openai", api_key="test"),
}

with patch("src.llm.router.get_settings", return_value=mock_settings):
    # Claude prefix → AnthropicAdapter
    a = route("claude-sonnet-4-6")
    check("claude- → AnthropicAdapter", type(a).__name__ == "AnthropicAdapter")

    # GPT prefix → OpenAICompatAdapter
    a = route("gpt-4o-mini")
    check("gpt- → OpenAICompatAdapter", type(a).__name__ == "OpenAICompatAdapter")

    # Gemini prefix → OpenAICompatAdapter
    a = route("gemini-2.5-pro")
    check("gemini- → OpenAICompatAdapter", type(a).__name__ == "OpenAICompatAdapter")

    # Tier resolution: medium → claude → AnthropicAdapter
    a = route("medium")
    check("medium tier → AnthropicAdapter", type(a).__name__ == "AnthropicAdapter")

    # Tier resolution: light → gpt → OpenAICompatAdapter
    a = route("light")
    check("light tier → OpenAICompatAdapter", type(a).__name__ == "OpenAICompatAdapter")

# ── 13. kwargs forwarding ───────────────────────────────

print("\n=== 13. kwargs forwarding ===")

req = adapter._build_request(
    [{"role": "user", "content": "hi"}],
    temperature=0.5,
    max_tokens=1000,
)
check("temperature forwarded", req["temperature"] == 0.5)
check("max_tokens overridden", req["max_tokens"] == 1000)

# ── 14. Edge cases ──────────────────────────────────────

print("\n=== 14. Edge cases ===")

# Assistant with content + tool_calls
req = adapter._build_request([
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "Let me check.", "tool_calls": [
        {"id": "tc_1", "function": {"name": "shell", "arguments": {"command": "pwd"}}}
    ]},
])
asst_blocks = req["messages"][1]["content"]
check("text + tool_use blocks", len(asst_blocks) == 2)
check("first is text", asst_blocks[0]["type"] == "text")
check("second is tool_use", asst_blocks[1]["type"] == "tool_use")

# Empty content assistant with tool_calls only
req = adapter._build_request([
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "tc_1", "function": {"name": "shell", "arguments": {"command": "pwd"}}}
    ]},
])
asst_blocks = req["messages"][1]["content"]
check("tool_use only (no empty text)", len(asst_blocks) == 1 and asst_blocks[0]["type"] == "tool_use")

# data URI parsing edge case
media_type, data = AnthropicAdapter._parse_data_uri("data:image/jpeg;base64,/9j/4AAQ")
check("jpeg media_type", media_type == "image/jpeg")
check("jpeg data", data == "/9j/4AAQ")

# Non-data-URI fallback
media_type, data = AnthropicAdapter._parse_data_uri("https://example.com/img.png")
check("URL fallback media_type", media_type == "image/png")

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
