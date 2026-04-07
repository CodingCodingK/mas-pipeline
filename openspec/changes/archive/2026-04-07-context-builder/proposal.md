## Why

agent_loop 已完成，但目前测试脚本是手动构造 messages 列表。需要一个 context-builder 来解析 Agent 角色文件（`agents/*.md`）、构建 system prompt、组装完整的 messages 列表，为 Phase 1 验收（端到端单 Agent）提供最后一块拼图。

## What Changes

- 新增角色文件解析：读取 `agents/*.md`，分离 YAML frontmatter（model_tier, tools, description）和正文
- 新增 `build_system_prompt()`：分层拼接 identity + role + memory 占位 + skill 占位
- 新增 `build_messages()`：组装 `[system, ...history, user]` 的 OpenAI dict 列表
- 新增第一个角色文件 `agents/general.md`
- 新增 Phase 1 端到端验收脚本 `scripts/test_single_agent.py`（真实调 LLM）

## Capabilities

### New Capabilities
- `context-builder`: System prompt 构建和 messages 组装 — 角色文件解析、分层 prompt、runtime context 注入

### Modified Capabilities

（无。agent-loop 的 spec 不需要修改，context-builder 是 agent_loop 的上游准备。）

## Impact

- 新增 `src/agent/context.py`
- 新增 `agents/general.md`
- 新增 `scripts/test_single_agent.py`（Phase 1 验收）
- 依赖 PyYAML（已有，config 系统使用）
- 依赖 `src/agent/state.py`（AgentState）、`src/agent/loop.py`（agent_loop）
- 依赖 `src/llm/router.py`（route）、`src/tools/registry.py`（ToolRegistry）
