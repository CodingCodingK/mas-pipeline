## Context

当前 Agent 的行为完全由 role prompt + tools 决定。`src/agent/context.py` 的 `_skill_layer()` 返回 None（Phase 5 占位）。需要实现 Skill 系统，让开发者把工作流封装为 `.md` 文件，LLM 可以主动发现和调用。

参考 CC Skill 系统的层级概念：文件定义 → 加载发现 → system prompt 摘要 → SkillTool 调用 → inline/fork 执行。我们只做文件 skills，不做 bundled/MCP/plugin/conditional skills。

现有代码：
- `src/agent/context.py` — `_skill_layer()` 占位，`build_system_prompt` 4 层拼接
- `src/agent/factory.py` — create_agent 已有 tools 白名单、permission_mode、hook_runner
- `src/tools/builtins/__init__.py` — get_all_tools 返回所有内置工具
- `src/tools/builtins/spawn_agent.py` — fork 模式可复用其 create_agent + run_agent_to_completion 模式

## Goals / Non-Goals

**Goals:**
- `skills/*.md` 文件加载为 SkillDefinition
- SkillTool 供 LLM 按 `{skill_name, args}` 调用
- inline 模式：变量替换后注入当前对话
- fork 模式：spawn 隔离子 agent 执行，返回结果
- `_skill_layer()` 注入 always skills 全文 + 按需 skills XML 摘要
- role frontmatter `skills: [...]` 白名单过滤

**Non-Goals:**
- Bundled skills（编译到代码中的 skill）
- MCP skills / Plugin skills
- 条件激活（paths 字段触发）
- Skill hooks
- `disableModelInvocation` 字段
- Skill 权限独立管理（走现有 Permission 系统）

## Decisions

### D1: Skill 文件格式

```yaml
# skills/research.md
---
name: research
description: 深度调研指定主题，搜索多个来源并交叉验证
when_to_use: 当需要对某个技术主题、概念或问题进行全面调研时
context: fork
model_tier: medium
tools: [web_search, read_file]
always: false
arguments: topic
---

请对以下主题进行深度调研：$ARGUMENTS

要求：
1. 搜索至少 3 个来源
2. 交叉验证关键事实
3. 输出结构化调研报告
```

字段设计参考 CC，简化版：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | 文件名去 .md | 显示名 |
| description | str | "" | 短描述，用于 XML 摘要 |
| when_to_use | str | "" | LLM 判断何时触发 |
| context | str | "inline" | "inline" 或 "fork" |
| model_tier | str | "inherit" | fork 子 agent 模型层级 |
| tools | list[str] | [] | fork 子 agent 可用工具 |
| always | bool | false | true = 全文注入 system prompt |
| arguments | str | "" | 参数提示（如 "topic"） |

body 是 prompt 模板，支持变量替换。

### D2: 加载与发现

```python
# src/skills/loader.py
SKILLS_DIR = Path("skills/")  # 项目根目录下

def load_skills(skills_dir: Path | None = None) -> dict[str, SkillDefinition]:
    """扫描目录下所有 .md 文件，解析为 SkillDefinition。"""

def load_skill(path: Path) -> SkillDefinition:
    """解析单个 skill 文件。"""
```

复用 `parse_role_file` 的 frontmatter 解析逻辑（已在 context.py 中）。

### D3: 变量替换

```python
VARIABLES = {
    "$ARGUMENTS": args,            # 完整参数字符串
    "${PROJECT_ID}": project_id,   # 当前项目 ID
    "${AGENT_ID}": agent_id,       # 当前 agent ID
    "${SKILL_DIR}": skill_dir,     # skill 文件所在目录
}
```

替换逻辑：简单字符串替换（`str.replace`），不需要 shell-style 解析。CC 用 `$ARGUMENTS`，我们保持一致。

### D4: 执行模式

**inline 执行：**
```
SkillTool.call({skill_name: "summarize", args: "..."})
    → substitute_variables(skill.content, args, context)
    → 返回 ToolResult(output=substituted_content, metadata={status: "inline"})
    → agent_loop 把 output 当作指令继续执行
```

inline 不 spawn 子 agent。skill body 替换后作为 ToolResult.output 返回给 LLM，LLM 读到后按指令执行。这和 CC 的 inline 行为一致——skill 内容展开到对话中。

**fork 执行：**
```
SkillTool.call({skill_name: "research", args: "Redis pub/sub"})
    → substitute_variables(skill.content, args, context)
    → create_agent(role=skill_name, task_description=substituted, tools=skill.tools, ...)
    → run_agent_to_completion(state)
    → extract_final_output(state.messages)
    → 返回 ToolResult(output=final_output, metadata={status: "forked"})
```

fork 模式复用 spawn_agent 的 create_agent + run_agent_to_completion 模式，但**同步等待**（不像 spawn_agent 是异步通知）。

**Why 同步不异步：** CC 的 fork skill 也是同步等待（`await runAgent()`）。skill 调用者需要结果来继续工作，异步不合适。

### D5: SkillTool 设计

```python
class SkillTool(Tool):
    name = "skill"
    input_schema = {
        "properties": {
            "skill_name": {"type": "string"},
            "args": {"type": "string", "default": ""},
        },
        "required": ["skill_name"],
    }
```

SkillTool 需要知道可用 skills 列表（用于验证 skill_name）。通过 ToolContext 传递 `available_skills: dict[str, SkillDefinition]`。

### D6: System Prompt 集成

`_skill_layer(skills)` 返回两部分拼接：

```
# Always-On Skills
（always=true 的 skill 全文内容）

# Available Skills
<skills>
  <skill name="research">
    <description>深度调研指定主题</description>
    <when-to-use>当需要对某个技术主题进行全面调研时</when-to-use>
    <arguments>topic</arguments>
  </skill>
  <skill name="summarize">
    ...
  </skill>
</skills>

Use the `skill` tool to invoke a skill when it matches your current task.
```

XML 格式让 LLM 容易解析。CC 也用类似的结构化格式在 system-reminder 中展示可用 skills。

### D7: Role Frontmatter Skills 白名单

```yaml
# agents/researcher.md
---
name: researcher
model_tier: medium
tools: [web_search, read_file]
skills: [research]
---
```

create_agent 加载时：
1. 加载所有 skills（`load_skills()`）
2. 按 frontmatter `skills` 字段过滤
3. 传给 `build_system_prompt(skill_definitions=filtered_skills)`
4. 如果有按需 skill，注册 SkillTool 到 ToolRegistry

**未声明 skills 字段 = 无 skill 可用**（安全默认，和 tools 逻辑一致）。

### D8: SkillTool 注册策略

SkillTool 不是全局注册到 `get_all_tools()`，而是按需注册：

- 如果 agent 有可用的按需 skills → 注册 SkillTool（携带 skills 列表）
- 如果 agent 只有 always skills 或没有 skills → 不注册 SkillTool（零开销）

SkillTool 实例化时传入 `available_skills` 字典，每个 agent 的 SkillTool 实例不同。

### D9: Fork 模式的 Permission 传递

fork 创建的子 agent 需要继承父 agent 的 permission_mode 和 deny 规则。复用 Permission 的 `parent_deny_rules` 机制，与 SpawnAgentTool 一致。

## Risks / Trade-offs

- **[inline skill 消耗 token]** → inline 的 skill body 作为 ToolResult 返回，占当前窗口。长 skill 应该用 fork 模式。开发者自行选择。
- **[fork 同步阻塞]** → fork 执行是 await，当前 agent 暂停。但 skill 调用者需要结果继续，异步不实际。
- **[SkillTool 每 agent 不同实例]** → 不能放 get_all_tools() 单例。需要在 create_agent 时动态创建并注册。稍增复杂但逻辑正确。
- **[skills 目录固定路径]** → 只支持项目根目录 `skills/`。CC 支持多层目录发现，我们简化为单目录。
