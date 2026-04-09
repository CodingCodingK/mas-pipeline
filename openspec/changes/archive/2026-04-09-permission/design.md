## Context

当前工具访问控制只有一层：role frontmatter 的 `tools` 白名单决定 agent 能"看到"哪些工具。但无法做参数级精细控制（如允许 shell 但禁 `rm -rf`、允许写文件但禁写 `/etc`）。Phase 5.1 Hooks 已完成，PreToolUse hook 可以 deny/modify/allow，Permission 作为 hook 的消费者接入。

现有代码：
- `src/hooks/` — HookRunner + 9 事件 + command/prompt 两种执行器
- `src/agent/factory.py` — create_agent，已有 `_build_hook_runner` 构建 HookRunner
- `src/engine/pipeline.py` — execute_pipeline，已有 hook_runner 参数
- `src/permissions/` — 空占位文件

## Goals / Non-Goals

**Goals:**
- 实现 `PermissionRule` 规则引擎：`ToolName(fnmatch_pattern)` 语法，支持 tool name + 参数内容匹配
- 三种运行模式：bypass / normal / strict
- ask 机制：`asyncio.Future` 暂停等待外部回复，默认 fallback deny
- 注册为 PreToolUse hook，统一入口
- SubAgent 继承父级 deny 规则
- permission_mode 只在最外层入口（execute_pipeline）给默认值，内部层层必传

**Non-Goals:**
- 交互式 UI（Phase 6）
- 动态规则热更新（运行中改规则）
- ML 分类器自动判定（CC 的 auto mode）
- per-user 权限配置（当前无多用户场景）

## Decisions

### D1: Permission 模块结构

```
src/permissions/
    __init__.py
    types.py       — PermissionMode, PermissionRule, PermissionResult
    checker.py     — check_permission() 纯函数 + PermissionChecker 类
    hooks.py       — register_permission_hooks() 便利函数
```

**Why:** 规则判定逻辑（checker.py）与 hook 注册（hooks.py）分离。checker 是纯函数方便单测，hooks.py 知道 HookRunner 但只做薄适配。

### D2: 规则语法 — `ToolName(fnmatch_pattern)`

```python
"bash"                    # 匹配所有 bash 调用
"bash(git *)"             # 匹配 command 以 git 开头
"write(/etc/*)"           # 匹配 file_path 在 /etc 下
"read_file(*.env)"        # 匹配读 .env 文件
```

解析为：
```python
@dataclass
class PermissionRule:
    tool_name: str              # 精确匹配（小写）
    pattern: str | None         # fnmatch glob，None = 匹配所有
    action: str                 # "allow" | "deny" | "ask"
```

参数字段映射表（确定 pattern 匹配哪个参数）：
```python
TOOL_CONTENT_FIELD: dict[str, str] = {
    "shell": "command",
    "write": "file_path",
    "read_file": "file_path",
    "edit": "file_path",
    "web_search": "query",
}
# 未登记的工具：只匹配 tool_name，pattern 部分忽略
```

**Why:** 参考 CC 的 `ToolName(content)` 语法。CC 每个 Tool 自己实现 checkPermissions，我们用映射表统一处理，新增工具只需加一行映射。fnmatch 是标准库，零依赖。

**Alternative:** 正则表达式——更强大但配置门槛高，fnmatch 对运维人员更友好。

### D3: 三种模式

```python
class PermissionMode(str, Enum):
    BYPASS = "bypass"     # 跳过所有规则检查，直接 allow
    NORMAL = "normal"     # 按规则判定 allow/deny/ask
    STRICT = "strict"     # ask → deny（无人值守安全模式）
```

传递链路：
```
execute_pipeline(permission_mode=NORMAL)     # 唯一默认值
    → create_agent(permission_mode)          # 必传
        → PermissionChecker(mode)            # 必传
```

Phase 6 API 从前端请求读 mode，传入 execute_pipeline。

### D4: check_permission 判定逻辑

```python
def check_permission(tool_name, params, rules, mode) -> PermissionResult:
    # 1. bypass → 直接 allow
    if mode == BYPASS:
        return PermissionResult("allow")

    # 2. 收集匹配的规则
    matched = [r for r in rules if _rule_matches(r, tool_name, params)]

    # 3. 无匹配规则 → allow（默认放行）
    if not matched:
        return PermissionResult("allow")

    # 4. deny 优先
    if any(r.action == "deny" for r in matched):
        deny_rule = next(r for r in matched if r.action == "deny")
        return PermissionResult("deny", reason=f"Denied by rule: {deny_rule}")

    # 5. ask 处理
    if any(r.action == "ask" for r in matched):
        if mode == STRICT:
            return PermissionResult("deny", reason="ask→deny in strict mode")
        return PermissionResult("ask")

    # 6. 全是 allow
    return PermissionResult("allow")
```

deny 永远优先，与 HookResult 的 aggregate_results 一致。

### D5: ask 机制

```python
@dataclass
class PermissionResult:
    action: str                    # "allow" | "deny" | "ask"
    reason: str = ""
    future: asyncio.Future | None = None   # ask 时由 hook 创建
```

ask 流程：
1. checker 返回 `PermissionResult(action="ask", future=future)`
2. hook 包装层 `await future`（agent loop 暂停）
3. 外部 responder 调 `future.set_result("allow"/"deny")`
4. 无 responder 时，配合 timeout（默认 0 = 无限等待），无 responder 注册则立即 fallback deny

Phase 6 API handler 注册 responder，通过 WebSocket 推给前端。

### D6: SubAgent deny 继承

create_agent 新增 `parent_deny_rules: list[PermissionRule] | None = None`。

spawn_agent 调 create_agent 时，从父 agent 的 PermissionChecker 提取 deny 规则传给子 agent。子 agent 的 checker 合并父级 deny + 自身规则。

**Why:** 安全红线不能被子 agent 绕过。不继承 allow 是因为子 agent 可能有不同角色，父级的 allow 不一定适用。

### D7: 配置结构

```yaml
# settings.yaml
permissions:
  deny:
    - "bash(rm -rf *)"
    - "write(/etc/*)"
  allow:
    - "read_file"
    - "bash(git *)"
  ask:
    - "shell"
```

加载后解析为 `list[PermissionRule]`，deny 列表和 allow 列表合并。

### D8: hook 注册方式

```python
# src/permissions/hooks.py
def register_permission_hooks(
    hook_runner: HookRunner,
    rules: list[PermissionRule],
    mode: PermissionMode,
) -> None:
    """把 Permission 规则注册为 PreToolUse hook。"""
    # 内部注册一个自定义 executor 类型的 hook
    # HookRunner 需要扩展：支持 callable executor（不只是 command/prompt）
```

HookRunner 需要小改动：`_execute_one` 支持第三种执行器类型 `callable`，即直接调用一个 async 函数。这比把 Permission 包装成 command subprocess 或 prompt LLM 调用更自然。

```python
# hooks/config.py — 新增
@dataclass
class HookConfig:
    type: str           # "command" | "prompt" | "callable"
    command: str = ""
    prompt: str = ""
    callable: Callable | None = None   # 新增：直接传 async 函数
    timeout: int = 30
```

## Risks / Trade-offs

- **[fnmatch 局限]** → fnmatch 不支持 `**` 递归匹配。如果需要，可以后续换 pathlib.PurePath.match 或 wcmatch。当前场景够用。
- **[ask 无 UI]** → 现在没有 responder，ask 行为等同 deny。Phase 6 接通后自动生效，无需改 Permission 代码。
- **[callable hook 是内部扩展]** → 外部用户仍然只能配 command/prompt。callable 是 Permission 等内部模块的注册方式，不暴露到 YAML 配置。
- **[SubAgent deny 继承深度]** → 只传一层 parent_deny_rules，不做递归累加。子 agent 再 spawn 子 agent 时，它自己的 deny（含继承的）自然作为新的 parent_deny_rules 传下去。
