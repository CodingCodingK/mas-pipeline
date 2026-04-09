## ADDED Requirements

### Requirement: SkillTool accepts skill_name and args parameters
SkillTool SHALL have name="skill" and accept input parameters: skill_name (string, required) and args (string, optional, default "").

#### Scenario: Input schema
- **WHEN** SkillTool.input_schema is inspected
- **THEN** it SHALL require "skill_name" and have optional "args"

### Requirement: SkillTool validates skill_name against available skills
SkillTool SHALL validate that skill_name exists in its available_skills dict. If not found, it SHALL return a ToolResult with success=False.

#### Scenario: Valid skill name
- **WHEN** SkillTool.call is invoked with skill_name="research" and "research" is in available_skills
- **THEN** it SHALL proceed to execute the skill

#### Scenario: Invalid skill name
- **WHEN** SkillTool.call is invoked with skill_name="nonexistent"
- **THEN** it SHALL return ToolResult(output="Skill 'nonexistent' not found", success=False)

### Requirement: SkillTool dispatches to inline or fork based on skill context
SkillTool.call SHALL check the skill's context field and dispatch to execute_inline for "inline" skills and execute_fork for "fork" skills.

#### Scenario: Inline skill dispatch
- **WHEN** skill_name refers to a skill with context="inline"
- **THEN** SkillTool SHALL call execute_inline and return ToolResult with the substituted content and metadata={status: "inline", skill_name: name}

#### Scenario: Fork skill dispatch
- **WHEN** skill_name refers to a skill with context="fork"
- **THEN** SkillTool SHALL call execute_fork and return ToolResult with the agent output and metadata={status: "forked", skill_name: name}

### Requirement: SkillTool is instantiated per-agent with available skills
SkillTool SHALL accept an `available_skills: dict[str, SkillDefinition]` parameter at construction time. Each agent gets its own SkillTool instance with its filtered skills.

#### Scenario: Per-agent skills
- **WHEN** two agents have different skill lists
- **THEN** each SHALL have a separate SkillTool instance with only their allowed skills
