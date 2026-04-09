## Why

Agent 工具调用目前没有拦截机制——LLM 请求什么工具就直接执行，没有权限检查、没有审计、没有自定义校验。Hooks 是整个 Extension Layer 的地基：Permission（5.2）通过 PreToolUse hook 实现拦截，Telemetry（Phase 6）通过 PostToolUse hook 采集数据，生命周期事件为监控和编排提供插入点。

## What Changes

- 新增 9 种 Hook 事件：PreToolUse / PostToolUse / PostToolUseFailure（工具相关）、SessionStart / SessionEnd（会话生命周期）、SubagentStart / SubagentEnd（子 Agent 生命周期）、PipelineStart / PipelineEnd（管线生命周期）
- 新增 2 种 Hook 执行器：command（子进程 stdin/stdout JSON 协议）、prompt（调 light 模型评估）
- 新增 HookRunner：注册、匹配、并行执行 hooks，返回聚合结果
- 新增 HookResult：action（allow/deny/modify）+ reason + updated_input + additional_context
- 修改 ToolOrchestrator：在 tool.call() 前后插入 PreToolUse / PostToolUse / PostToolUseFailure hook 调用
- 修改 spawn_agent：在子 Agent 启动和完成时触发 SubagentStart / SubagentEnd 事件
- 修改 pipeline engine：在管线执行开始和结束时触发 PipelineStart / PipelineEnd 事件
- 配置来源：settings.yaml hooks 节（全局）+ Agent .md frontmatter hooks（角色级）

## Capabilities

### New Capabilities
- `hook-events`: Hook 事件类型定义（9 种事件枚举 + HookEvent/HookResult dataclass）
- `hook-runner`: Hook 执行引擎（注册、匹配、command/prompt 执行器、并行执行、超时控制）
- `hook-config`: Hook 配置加载（settings.yaml + agent frontmatter 解析、matcher 匹配规则）

### Modified Capabilities
- `tool-execution`: ToolOrchestrator 在 tool.call() 前后调用 PreToolUse / PostToolUse / PostToolUseFailure hooks
- `spawn-agent`: 子 Agent 启动和完成时触发 SubagentStart / SubagentEnd 事件
- `pipeline-execution`: 管线执行开始和结束时触发 PipelineStart / PipelineEnd 事件

## Impact

- 新增目录：`src/hooks/`（types.py, runner.py, config.py）
- 修改文件：`src/tools/orchestrator.py`、`src/tools/builtins/spawn_agent.py`、`src/engine/pipeline.py`
- 配置新增：`settings.yaml` 增加 `hooks` 节
- Agent frontmatter 新增可选 `hooks` 字段
- 依赖：无新外部依赖（subprocess 和 LLM adapter 都已有）
- SessionStart / SessionEnd 事件类型先定义，集成点在 Phase 6 API 层接入时补
