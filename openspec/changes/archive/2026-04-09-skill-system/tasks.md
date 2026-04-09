## 1. Core Types & Loader

- [x] 1.1 Create `src/skills/__init__.py` module init
- [x] 1.2 Create `src/skills/types.py` — SkillDefinition dataclass, SkillResult dataclass
- [x] 1.3 Implement `src/skills/loader.py` — load_skill(path), load_skills(skills_dir), frontmatter parsing, default values

## 2. Variable Substitution & Execution

- [x] 2.1 Implement `substitute_variables(content, args, context)` in `src/skills/executor.py` — $ARGUMENTS, ${PROJECT_ID}, ${AGENT_ID}, ${SKILL_DIR}
- [x] 2.2 Implement `execute_inline(skill, args, context)` — substitute + return SkillResult(mode="inline")
- [x] 2.3 Implement `execute_fork(skill, args, context)` — substitute + create_agent + run_agent_to_completion + extract output, inherit permission_mode + parent_deny_rules

## 3. SkillTool

- [x] 3.1 Implement `src/tools/builtins/skill.py` — SkillTool class with input_schema {skill_name, args}, available_skills dict at construction
- [x] 3.2 SkillTool.call: validate skill_name, dispatch to execute_inline or execute_fork, return ToolResult with metadata

## 4. Context Builder Integration

- [x] 4.1 Implement `_skill_layer(skills)` in `src/agent/context.py` — always skills full content + on-demand skills XML summary
- [x] 4.2 Update `build_system_prompt` signature — add `skill_definitions` parameter, pass to `_skill_layer`

## 5. Factory Integration

- [x] 5.1 Update `create_agent` — load skills via load_skills(), filter by frontmatter `skills` field, pass to build_system_prompt
- [x] 5.2 Register SkillTool per-agent — if agent has on-demand skills, create SkillTool instance and register to ToolRegistry
- [x] 5.3 Pass available_skills to ToolContext (via SkillTool instance, not ToolContext) for SkillTool access in fork execution

## 6. Preset Skills

- [x] 6.1 Create `skills/research.md` — fork mode, tools: [web_search, read_file], deep research template
- [x] 6.2 Create `skills/summarize.md` — inline mode, summarization prompt template

## 7. Tests

- [x] 7.1 Unit tests for types: SkillDefinition defaults, SkillResult construction
- [x] 7.2 Unit tests for loader: load_skill (full/minimal/no frontmatter), load_skills (multiple/empty/nonexistent dir)
- [x] 7.3 Unit tests for executor: substitute_variables (all vars, missing values, no vars), execute_inline, execute_fork (mock create_agent)
- [x] 7.4 Unit tests for SkillTool: valid/invalid skill_name, inline dispatch, fork dispatch, per-agent skills
- [x] 7.5 Unit tests for context builder: _skill_layer (always/on-demand/empty/mixed), build_system_prompt with skills
- [x] 7.6 Integration tests: create_agent with skills whitelist, create_agent without skills, SkillTool registered when on-demand skills exist

## 8. Docs

- [x] 8.1 Update `.plan/progress.md` — mark Phase 5.3 Skill complete
- [x] 8.2 Add skill design notes to `.plan/skill_design_notes.md`
