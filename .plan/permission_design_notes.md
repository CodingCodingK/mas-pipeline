# Permission 系统设计笔记

## 核心架构

Permission 不是独立管线，而是注册为 PreToolUse hook。统一入口，Orchestrator 只有一个拦截点。

```
execute_pipeline(permission_mode=NORMAL)          # 唯一默认值
    → create_agent(permission_mode=NORMAL)        # 必传
        → PermissionChecker(rules, mode)          # 必传
            → register_permission_hooks(runner, checker)
                → HookRunner PRE_TOOL_USE callable hook
```

## 三种模式

| 模式 | 行为 | 场景 |
|------|------|------|
| bypass | 跳过所有检查 | 开发调试 |
| normal | 按规则判定 allow/deny/ask | 默认模式 |
| strict | ask→deny | 无人值守批处理 |

## 规则语法

```
ToolName(fnmatch_pattern)
```

示例：
- `"shell"` — 匹配所有 shell 调用
- `"shell(git *)"` — 仅匹配 git 命令
- `"write(/etc/*)"` — 匹配写入 /etc 下的文件
- `"read_file(*.env)"` — 匹配读取 .env 文件

## 参数字段映射

每个工具匹配哪个参数：

| 工具 | 匹配字段 |
|------|----------|
| shell | command |
| write | file_path |
| read_file | file_path |
| edit | file_path |
| web_search | query |

未登记的工具只支持 tool_name 级规则。

## 判定优先级

```
bypass → 直接 allow
无匹配规则 → allow（默认放行）
deny → 最高优先级
ask → normal 模式暂停等待，strict 模式降级 deny
allow → 最低优先级
```

## SubAgent 继承

- 子 agent 继承父级 **deny** 规则（安全红线不可绕过）
- 子 agent **不继承** 父级 allow（不同角色可能有不同权限）
- 传递路径：`parent_checker.get_deny_rules()` → `create_agent(parent_deny_rules=...)`

## ask 机制（Phase 6 接通）

当前状态：ask → fallback deny（无 responder）

Phase 6 计划：
1. API handler 注册 responder
2. WebSocket 推送 permission request 给前端
3. 前端用户点击 Allow/Deny
4. `future.set_result("allow"/"deny")` 恢复 agent loop

## CC 对比

| 维度 | CC | 我们 |
|------|-----|------|
| 规则语法 | `ToolName(pattern)` | 相同 |
| 参数匹配 | 每个 Tool 自定义 checkPermissions | 统一映射表 |
| pattern | exact + prefix + wildcard + gitignore | fnmatch（标准库） |
| action | allow / deny / ask | 相同 |
| 规则来源 | 5 层配置 | 2 层（settings + pipeline） |
| 集成方式 | Tool 各自调用 | PreToolUse hook 统一拦截 |
| 超时 | 无超时（无限等待 + AbortSignal） | 同上 |

## 配置示例

```yaml
# settings.yaml
permissions:
  deny:
    - "shell(rm -rf *)"
    - "write(/etc/*)"
  allow:
    - "read_file"
    - "shell(git *)"
  ask:
    - "shell"
```

## 文件结构

```
src/permissions/
    __init__.py      # 模块声明
    types.py         # PermissionMode, PermissionRule, PermissionResult, TOOL_CONTENT_FIELD
    rules.py         # parse_rule, rule_matches, check_permission, load_permission_rules
    checker.py       # PermissionChecker 类
    hooks.py         # register_permission_hooks 便利函数
```
