## 1. 角色文件解析

- [x] 1.1 实现 `src/agent/context.py` — `parse_role_file(path) -> tuple[dict, str]`：分离 YAML frontmatter 和 markdown body
- [x] 1.2 创建 `agents/general.md` — frontmatter(description, model_tier: medium, tools: [read_file, shell]) + 通用助手正文

## 2. System Prompt 构建

- [x] 2.1 实现 `build_system_prompt(role_body, project_root) -> str`：拼接 identity 层（OS、Python 版本、项目路径）+ role 层 + memory/skill 占位
- [x] 2.2 实现 `build_messages(system_prompt, history, user_input, runtime_context) -> list[dict]`：组装 [system, ...history, user]，runtime_context 追加到 system prompt 末尾

## 3. 验证

- [x] 3.1 创建 `scripts/test_context_builder.py` — 验证 parse_role_file、build_system_prompt、build_messages 的格式正确性
- [x] 3.2 创建 `scripts/test_single_agent.py` — Phase 1 端到端验收：parse role → build prompt → build messages → AgentState → agent_loop → 真实 LLM 调用 → tool call → 最终回复
