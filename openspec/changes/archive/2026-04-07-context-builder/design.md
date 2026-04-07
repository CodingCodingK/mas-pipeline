## Context

Phase 1.3 agent-loop 完成，ReAct 循环已能驱动 LLM + 工具执行。但 agent_loop 接收的是已构造好的 `state.messages`，目前由测试脚本手动拼装。需要 context-builder 来：
1. 解析 Agent 角色文件（`agents/*.md`）的 frontmatter 和正文
2. 分层构建 system prompt
3. 组装完整的 messages 列表供 agent_loop 消费

参考 CC 的 `getSystemPrompt()`（prompts.ts:444）分层架构，简化为 4 层。

## Goals / Non-Goals

**Goals:**
- 解析 `agents/*.md` 角色文件（YAML frontmatter + markdown body）
- 分层 system prompt：identity → role → memory(占位) → skill(占位)
- 组装 messages 列表：system + history + user，附带 runtime context
- 端到端验收：真实 LLM 调用验证完整 Phase 1 链路

**Non-Goals:**
- 不实现 memory 层内容（Phase 3）
- 不实现 skill 层内容（Phase 5）
- 不实现 prompt caching 优化（CC 的 static/dynamic boundary）
- 不实现 create_agent 工厂函数（Phase 2.5）

## Decisions

### D1: Frontmatter 解析 — 手写 10 行 vs python-frontmatter 包

**选择：** 手写，用已有的 PyYAML。

```python
def parse_role_file(path):
    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm), body.strip()
    return {}, text.strip()
```

**理由：** 不引入新依赖。frontmatter 格式简单固定（description, model_tier, tools），不需要包的额外功能。

### D2: System prompt 分层 — 字符串拼接

**选择：** `build_system_prompt()` 按固定顺序拼接各层，每层返回 `str | None`，None 跳过。

```
identity:  平台信息（OS、Python 版本、项目路径、当前时间）
role:      角色文件正文
memory:    Phase 3 占位，返回 None
skill:     Phase 5 占位，返回 None
```

**替代方案：** CC 的 section registry + 缓存（systemPromptSection）。

**理由：** CC 的 section 机制为 prompt caching 服务（static vs dynamic 分区）。我们不需要 caching，直拼即可。Phase 3/5 加入时替换 None 为实际内容。

### D3: build_messages 的 system prompt 位置 — messages[0]

**选择：** `{"role": "system", "content": ...}` 作为 messages 列表第一个元素。

**理由：** OpenAI 兼容 API 标准格式。Phase 4 Anthropic adapter 内部转换为独立 `system` 参数。

### D4: runtime_context 注入 — 拼在 system prompt 末尾

**选择：** `build_messages()` 接收可选 `runtime_context: dict`，以 `# Runtime Context` section 追加到 system prompt 末尾。

内容包括：当前日期时间、agent_id。

**理由：** CC 也是追加方式（`appendSystemContext`）。放末尾不影响 prompt cache 前缀（未来优化时有用）。

### D5: 与 agent_loop 的集成 — 外部构造，不侵入 loop

**选择：** 方式 A — 调用方在 agent_loop 之前用 context-builder 构造好 messages，传入 AgentState。agent_loop 不知道 context-builder 的存在。

**替代方案：** 方式 B — agent_loop 内部第一轮调 context-builder。

**理由：** 职责分离。Phase 2.5 的 create_agent 工厂函数将封装 context-builder + AgentState 构造。

## Risks / Trade-offs

- **[角色文件格式简单]** → 只支持 YAML frontmatter + markdown body。如果将来需要更复杂格式（如 CC 的 JS agent definitions），需重构解析器。Phase 1 够用。
- **[无 prompt caching]** → 每轮 LLM 调用都发送完整 system prompt。短对话无影响，长对话成本高。Phase 3 compact 缓解，prompt caching 可在 adapter 层后续优化。
