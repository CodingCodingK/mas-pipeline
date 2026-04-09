## Why

Pipeline 引擎目前只通过 role frontmatter 的 `tools` 白名单控制工具可见性（researcher 只看到 web_search + read_file），但无法做参数级的精细控制——比如"允许 shell 但禁止 rm -rf"、"允许写文件但禁止写 /etc"。Permission 模块提供第二道防线，在工具调用前按规则判定 allow/deny/ask，通过已有的 PreToolUse hook 统一拦截。

## What Changes

- 新增 `src/permissions/` 模块：PermissionMode 枚举、PermissionRule 规则定义、规则匹配引擎、`register_permission_hooks()` 便利注册函数
- 规则语法 `ToolName(fnmatch_pattern)`：tool name 精确匹配 + 参数内容 fnmatch glob（通过 tool→字段映射表确定匹配哪个参数）
- 三种运行模式：bypass（全放行）、normal（按规则判）、strict（ask→deny，无人值守）
- ask 机制：`asyncio.Future` 暂停 agent loop，等外部 responder 回复；无 responder 时 fallback deny
- SubAgent 继承父级 deny 规则，不继承 allow
- permission_mode 只在最外层入口给默认值 `NORMAL`，内部层层必传
- 规则来源：settings.yaml `permissions` 段 + pipeline config 覆盖
- 默认无规则 = 全部 allow，不影响现有管线

## Capabilities

### New Capabilities
- `permission-rules`: 权限规则定义、解析、匹配引擎（PermissionRule、PermissionMode、check_permission、tool→字段映射表）
- `permission-integration`: Permission 模块注册为 PreToolUse hook、SubAgent deny 继承、permission_mode 传递链路

### Modified Capabilities
- `agent-factory`: create_agent 新增 permission_mode 参数，构建 PermissionChecker 并注册到 HookRunner
- `pipeline-execution`: execute_pipeline 新增 permission_mode 参数（最外层入口，默认 NORMAL），传递给 create_agent

## Impact

- 新增模块：`src/permissions/checker.py`（规则引擎）、`src/permissions/types.py`（PermissionMode、PermissionRule）、`src/permissions/hooks.py`（hook 注册）
- 修改：`src/agent/factory.py`（注入 permission）、`src/engine/pipeline.py`（传递 permission_mode）
- 配置：`src/project/config.py` Settings 新增 `permissions` 字段
- 依赖：仅 Python 标准库 fnmatch，零外部依赖
