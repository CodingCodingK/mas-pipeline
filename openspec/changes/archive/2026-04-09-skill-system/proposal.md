## Why

Agent 当前只能通过固定 role prompt 和 tool 调用工作，缺乏"可复用 prompt 模板"机制。开发者无法把常见工作流（调研、摘要、代码审查）封装为可被 LLM 主动发现和调用的 skill。CC 的 Skill 系统解决了这个问题——我们参考其流程和层级概念，实现文件 skills + inline/fork 两种执行模式。

## What Changes

- 新增 `src/skills/` 模块：SkillDefinition 定义、文件扫描加载、变量替换、inline/fork 执行
- 新增 `skills/` 目录：存放 `.md` 格式的 skill 文件（YAML frontmatter + prompt body）
- 新增 `SkillTool`：LLM 通过 `{skill_name, args}` 主动触发 skill
- 修改 Context Builder：`_skill_layer()` 从占位改为真实实现——always skill 全文注入，按需 skill XML 摘要
- 修改 role frontmatter：新增 `skills: [...]` 白名单字段，与 tools 模式一致
- 新增 2 个预制 skill：research（fork 模式）、summarize（inline 模式）
- **BREAKING**：create_agent 新增 `skills` 参数传递给 context builder

## Capabilities

### New Capabilities
- `skill-definition`: Skill 文件格式、SkillDefinition 数据结构、文件扫描加载
- `skill-execution`: inline/fork 两种执行模式、变量替换、SkillResult
- `skill-tool`: SkillTool 工具定义、LLM 调用 skill 的接口

### Modified Capabilities
- `context-builder`: `_skill_layer()` 从占位改为真实实现，注入 always skills 全文 + 按需 skills XML 摘要
- `agent-factory`: create_agent 新增 skills 加载、过滤、传递给 context builder；SkillTool 注入 ToolRegistry

## Impact

- 新增模块：`src/skills/loader.py`、`src/skills/executor.py`
- 新增工具：`src/tools/builtins/skill.py`
- 修改：`src/agent/context.py`（skill_layer 实现）、`src/agent/factory.py`（skills 加载 + SkillTool 注册）、`src/tools/builtins/__init__.py`（SkillTool 注册）
- 新增目录：`skills/`（预制 skill 文件）
- 依赖：仅 Python 标准库（re、fnmatch），零外部依赖
