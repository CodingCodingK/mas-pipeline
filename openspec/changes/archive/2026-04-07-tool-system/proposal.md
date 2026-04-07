## Why

Agent Loop（Phase 1.3）需要一个工具执行层：LLM 返回 tool_calls 后，系统必须能查找工具、校验参数、调度执行、返回结果。没有 tool-system，Agent 只能输出文本，无法与外部世界交互。

## What Changes

- 新增 `Tool` 抽象基类，定义工具的名称、描述、JSON Schema、并发安全性、执行接口
- 新增 `ToolResult` 数据结构，统一工具返回格式（output + success + metadata）
- 新增 `ToolRegistry`，管理工具注册、按名查找、导出 OpenAI function calling 格式定义
- 新增参数处理层：类型容错转换（cast）+ JSON Schema 校验（validate），校验失败返回 LLM 重试
- 新增 `ToolOrchestrator`，按并发安全性分批调度：连续 safe 工具并发（上限 10），非 safe 串行
- 新增两个内置工具：`read_file`（读文件，静态 safe）、`shell`（执行命令，动态判断 safe）

## Capabilities

### New Capabilities
- `tool-execution`: 工具基类、注册表、参数处理、调度执行的完整生命周期
- `tool-builtins`: 内置工具实现（read_file、shell），包括 shell 的动态安全判断和 cwd 持久化

### Modified Capabilities

（无，不修改已有 spec）

## Impact

- 新增模块：`src/tools/base.py`、`registry.py`、`orchestrator.py`、`builtins/read_file.py`、`builtins/shell.py`
- 被 Phase 1.3 agent-loop 直接依赖：Agent Loop 通过 Registry 获取工具定义传给 LLM，通过 Orchestrator 执行 tool_calls
- 依赖已有模块：`src/llm/adapter.py` 的 `ToolCallRequest` dataclass
- 无 API 变更、无数据库变更、无破坏性改动
