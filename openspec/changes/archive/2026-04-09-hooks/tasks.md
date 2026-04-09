## 1. Hook 事件类型

- [x] 1.1 创建 `src/hooks/__init__.py`
- [x] 1.2 创建 `src/hooks/types.py` — HookEventType 枚举（9 种事件）、HookEvent dataclass、HookResult dataclass
- [x] 1.3 实现 `aggregate_results(results: list[HookResult]) -> HookResult`：deny 优先、modify 取最后、additional_context 拼接

## 2. Hook 执行器

- [x] 2.1 创建 `src/hooks/executors.py` — command 执行器：asyncio.create_subprocess_exec, stdin 写 JSON, stdout 读 JSON, 退出码语义（0=allow, 2=deny, 其他=非阻塞错误）, 超时控制
- [x] 2.2 实现 prompt 执行器：调 route("light") adapter, $ARGUMENTS 替换, 解析 LLM 响应为 HookResult

## 3. HookRunner

- [x] 3.1 创建 `src/hooks/runner.py` — HookRunner 类：hooks 存储结构（dict[HookEventType, list[HookConfig]]）
- [x] 3.2 实现 `register(event_type, matcher, hook_config)` 方法
- [x] 3.3 实现 `run(event: HookEvent) -> HookResult`：matcher 过滤 → 并行执行匹配的 hooks → aggregate_results
- [x] 3.4 实现 matcher 匹配逻辑：None 匹配所有、`|` 分隔多个工具名

## 4. Hook 配置加载

- [x] 4.1 创建 `src/hooks/config.py` — HookConfig dataclass（type, command, prompt, timeout, matcher）
- [x] 4.2 实现 `load_hooks_from_settings(settings) -> list[tuple[HookEventType, str|None, HookConfig]]`：从 settings.yaml hooks 节解析
- [x] 4.3 实现 `load_hooks_from_frontmatter(frontmatter) -> list[tuple[HookEventType, str|None, HookConfig]]`：从 agent .md frontmatter 解析
- [x] 4.4 实现配置校验：type 只能是 command/prompt、command 类型必须有 command 字段、prompt 类型必须有 prompt 字段
- [x] 4.5 更新 `src/project/config.py` — Settings dataclass 增加 hooks 字段

## 5. Orchestrator 集成

- [x] 5.1 修改 `ToolOrchestrator.__init__` — 新增 `hook_runner: HookRunner | None = None` 参数
- [x] 5.2 修改 `_execute_one` — tool.call() 前调用 PreToolUse hooks：deny 返回错误 ToolResult、modify 替换 params
- [x] 5.3 修改 `_execute_one` — tool.call() 后调用 PostToolUse hooks（成功时）或 PostToolUseFailure hooks（失败时）：追加 additional_context
- [x] 5.4 更新 ToolContext — 新增 `hook_runner: HookRunner | None = None` 字段

## 6. 生命周期事件集成

- [x] 6.1 修改 `src/tools/builtins/spawn_agent.py` — call() 中触发 SubagentStart、后台协程完成时触发 SubagentEnd
- [x] 6.2 修改 `src/engine/pipeline.py` — execute_pipeline 入口触发 PipelineStart、出口触发 PipelineEnd
- [x] 6.3 修改 `src/agent/factory.py` — create_agent 时加载全局+角色 hooks、构建 HookRunner、注入 ToolOrchestrator

## 7. 测试

- [x] 7.1 创建 `scripts/test_hooks_unit.py` — HookEventType 枚举、HookEvent 构造、HookResult 聚合、matcher 匹配
- [x] 7.2 创建 `scripts/test_hooks_executors.py` — command 执行器（正常/deny/超时/非 JSON 输出）、prompt 执行器（mock LLM）
- [x] 7.3 创建 `scripts/test_hooks_orchestrator.py` — orchestrator 集成：PreToolUse deny 阻断、modify 替换参数、PostToolUse additional_context、无 HookRunner 时向后兼容
- [x] 7.4 创建 `scripts/test_hooks_lifecycle.py` — spawn_agent SubagentStart/End、pipeline PipelineStart/End 事件触发
- [x] 7.5 创建 `scripts/test_hooks_config.py` — settings.yaml 加载、frontmatter 加载、配置校验、全局+角色合并
- [x] 7.6 回归测试 — 运行现有 streaming/agent_loop/pipeline 测试确认无破坏
