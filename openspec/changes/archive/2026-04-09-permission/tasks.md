## 1. Core Types

- [x] 1.1 Create `src/permissions/types.py` — PermissionMode enum (bypass/normal/strict), PermissionRule dataclass (tool_name, pattern, action), PermissionResult dataclass (action, reason, matched_rule)
- [x] 1.2 Add TOOL_CONTENT_FIELD mapping dict (shell→command, write→file_path, read_file→file_path, edit→file_path, web_search→query)

## 2. Rule Engine

- [x] 2.1 Implement `parse_rule(rule_str, action)` — parse "bash(git *)" into PermissionRule, handle no-pattern and empty-parens cases
- [x] 2.2 Implement `rule_matches(rule, tool_name, params)` — tool_name exact match + fnmatch on content field via TOOL_CONTENT_FIELD
- [x] 2.3 Implement `check_permission(tool_name, params, rules, mode)` — bypass shortcut, collect matches, deny priority, ask→deny in strict, default allow
- [x] 2.4 Implement `load_permission_rules(permissions_config)` — parse settings dict {deny: [...], allow: [...], ask: [...]} into list[PermissionRule]

## 3. PermissionChecker Class

- [x] 3.1 Implement `PermissionChecker(rules, mode, parent_deny_rules)` in `src/permissions/checker.py` — merge parent deny rules, expose check() and get_deny_rules()

## 4. Hook Integration

- [x] 4.1 Extend HookConfig with `callable_fn: Callable | None = None` field, type value `"callable"`
- [x] 4.2 Extend HookRunner._execute_one to handle type="callable" — call callable_fn directly with HookEvent
- [x] 4.3 Implement `register_permission_hooks(hook_runner, checker)` in `src/permissions/hooks.py` — create async callable, register on PRE_TOOL_USE; skip registration if rules empty
- [x] 4.4 Ask fallback: when check_permission returns ask and no responder, return HookResult(action="deny", reason="no responder")

## 5. Factory & Pipeline Integration

- [x] 5.1 Add `permissions: dict = {}` field to Settings model in `src/project/config.py`
- [x] 5.2 Modify `create_agent` — add required `permission_mode: PermissionMode` param + optional `parent_deny_rules`, build PermissionChecker, call register_permission_hooks; skip if bypass mode
- [x] 5.3 Modify `execute_pipeline` — add `permission_mode: PermissionMode = PermissionMode.NORMAL` param, pass to all create_agent calls
- [x] 5.4 Modify SpawnAgentTool — extract parent deny rules from parent's PermissionChecker, pass as parent_deny_rules to create_agent

## 6. Tests

- [x] 6.1 Unit tests for types: PermissionMode enum values, PermissionRule construction, PermissionResult defaults, TOOL_CONTENT_FIELD entries
- [x] 6.2 Unit tests for rule engine: parse_rule (with/without pattern, empty parens), rule_matches (name match, pattern match/mismatch, unknown tool), check_permission (bypass, no rules, deny priority, ask in strict/normal, multiple deny)
- [x] 6.3 Unit tests for load_permission_rules: mixed config, empty config, missing keys
- [x] 6.4 Unit tests for PermissionChecker: check delegation, get_deny_rules, parent deny merge
- [x] 6.5 Unit tests for hook integration: callable executor in HookRunner, register_permission_hooks deny/allow/ask-fallback, empty rules no registration
- [x] 6.6 Integration tests: create_agent with permission_mode, execute_pipeline permission_mode passthrough, SubAgent deny inheritance via SpawnAgentTool

## 7. Config & Docs

- [x] 7.1 Update `.plan/progress.md` — mark Phase 5.2 Permission complete
- [x] 7.2 Add permission design notes to `.plan/permission_design_notes.md`
