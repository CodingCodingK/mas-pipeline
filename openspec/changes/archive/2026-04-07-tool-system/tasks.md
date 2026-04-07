## 1. 基础数据结构

- [x] 1.1 实现 `src/tools/base.py` — `ToolResult` dataclass（output, success, metadata）
- [x] 1.2 实现 `src/tools/base.py` — `ToolContext` dataclass（agent_id, run_id, project_id, abort_signal）
- [x] 1.3 实现 `src/tools/base.py` — `Tool` 抽象基类（name, description, input_schema, is_concurrency_safe, is_read_only, call）

## 2. 参数处理

- [x] 2.1 实现 `src/tools/params.py` — `cast_params(params, schema)` 类型容错转换（str→int/float/bool, float→int, str→list）
- [x] 2.2 实现 `src/tools/params.py` — `validate_params(params, schema)` JSON Schema 校验，返回错误字符串列表

## 3. 注册表

- [x] 3.1 实现 `src/tools/registry.py` — `ToolRegistry` 类：register / get / list_definitions（支持 names 过滤）

## 4. 调度器

- [x] 4.1 实现 `src/tools/orchestrator.py` — `partition_tool_calls()` 按 is_concurrency_safe 分批（连续 safe 合并，unsafe 独立）
- [x] 4.2 实现 `src/tools/orchestrator.py` — `ToolOrchestrator.dispatch()` 分批执行：safe 批 asyncio.gather（上限 10），unsafe 批串行；集成 cast → validate → call 流程；异常捕获返回 ToolResult

## 5. 内置工具 — read_file

- [x] 5.1 实现 `src/tools/builtins/read_file.py` — `ReadFileTool`：读文件内容，支持 offset/limit，行号输出，30000 字符截断，is_concurrency_safe=True 硬编码

## 6. 内置工具 — shell

- [x] 6.1 实现 `src/tools/builtins/shell.py` — `ShellTool` 核心：subprocess 执行，120s 超时，stdout+stderr 捕获，30000 字符截断，exit_code 记入 metadata
- [x] 6.2 实现 `src/tools/builtins/shell.py` — 动态 `is_concurrency_safe`：变量展开/重定向检测 + 复合命令拆分 + SAFE_PREFIXES 白名单匹配
- [x] 6.3 实现 `src/tools/builtins/shell.py` — cwd 持久化：_cwd 实例状态，命令执行后 pwd 更新

## 7. 集成验证

- [x] 7.1 编写 `scripts/test_tool_system.py` — 端到端验证：注册工具 → 构造 ToolCallRequest → Orchestrator dispatch → 验证 ToolResult
- [x] 7.2 验证并发调度：构造 [read_file, read_file, shell("rm x"), read_file] → 确认分批 [并发, 串行, 并发]
- [x] 7.3 验证参数容错：传 `{"timeout": "30"}` → cast 修正 → validate 通过 → 执行成功
- [x] 7.4 ruff check + import 验证通过
