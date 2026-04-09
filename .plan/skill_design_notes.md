# Skill System — Design Notes

## Overview

File-based skill system: `skills/*.md` files with YAML frontmatter + prompt body.
LLM discovers available skills via system prompt XML summary, invokes via SkillTool.

## Architecture

```
skills/*.md          → load_skills() → dict[name, SkillDefinition]
                                              │
role frontmatter     → skills: [name, ...]    │ filter
                                              ▼
                                   filtered_skills
                                    ┌─────┴─────┐
                            always=true    always=false
                                │               │
                    _skill_layer()      SkillTool(on_demand)
                    full content        registered to ToolRegistry
                    in system prompt    XML summary in system prompt
```

## Execution Modes

### inline
- substitute_variables → return as ToolResult
- LLM receives substituted prompt text, follows instructions in current conversation
- No sub-agent, no tool restrictions

### fork
- substitute_variables → create_agent → run_agent_to_completion → extract output
- Spawns isolated sub-agent with skill's own tools whitelist
- Synchronous await (caller blocks until fork completes)
- Inherits parent permission_mode + deny rules

## CC Comparison

| Aspect | CC | mas-pipeline |
|--------|-----|-------------|
| Skill sources | bundled + file + MCP + plugin + conditional | file only |
| File format | .md frontmatter + body | same |
| Execution | inline + agent-type | inline + fork |
| Discovery | system prompt XML | same pattern |
| Invocation | Skill tool | SkillTool |
| Conditional activation | paths field triggers | not implemented |
| disableModelInvocation | supported | not implemented |
| Permission | skill-level hooks | inherits parent Permission system |

## Key Decisions

1. **File-only skills** — no bundled/MCP/plugin/conditional. Keeps complexity minimal.
2. **Per-agent SkillTool instances** — each agent gets filtered skills from role frontmatter `skills: [...]`.
3. **Fork uses synchronous await** — unlike spawn_agent (async notification queue), fork blocks until completion because caller needs the result.
4. **always=true injects full content** — no SkillTool invocation needed, always present in system prompt.
5. **Variable substitution** — $ARGUMENTS, ${PROJECT_ID}, ${AGENT_ID}, ${SKILL_DIR}. Missing values → empty string.
6. **Fork inherits permission** — permission_mode + parent deny rules propagated via exec_ctx.

## File Structure

```
src/skills/
  __init__.py          # module init
  types.py             # SkillDefinition, SkillResult
  loader.py            # load_skill, load_skills, _parse_frontmatter
  executor.py          # substitute_variables, execute_inline, execute_fork

src/tools/builtins/
  skill.py             # SkillTool class

src/agent/
  context.py           # _skill_layer (modified)
  factory.py           # skills loading + filtering + SkillTool registration (modified)

skills/
  research.md          # preset: fork mode, web_search + read_file
  summarize.md         # preset: inline mode, structured summary
```

## Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| name | str | filename stem | Display name |
| description | str | "" | Short description for XML summary |
| when_to_use | str | "" | LLM trigger hint |
| context | str | "inline" | "inline" or "fork" |
| model_tier | str | "inherit" | Fork sub-agent model tier |
| tools | list[str] | [] | Fork sub-agent tool whitelist |
| always | bool | false | true = full content in system prompt |
| arguments | str | "" | Argument hint for LLM |
