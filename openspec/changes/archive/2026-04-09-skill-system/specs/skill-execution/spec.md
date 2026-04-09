## ADDED Requirements

### Requirement: substitute_variables replaces placeholders in skill content
`substitute_variables(content, args, context)` SHALL replace `$ARGUMENTS` with the args string, `${PROJECT_ID}` with context project_id, `${AGENT_ID}` with context agent_id, and `${SKILL_DIR}` with the skill directory path.

#### Scenario: Replace $ARGUMENTS
- **WHEN** content contains "$ARGUMENTS" and args is "Redis pub/sub"
- **THEN** "$ARGUMENTS" SHALL be replaced with "Redis pub/sub"

#### Scenario: Replace ${PROJECT_ID}
- **WHEN** content contains "${PROJECT_ID}" and context.project_id is 42
- **THEN** "${PROJECT_ID}" SHALL be replaced with "42"

#### Scenario: No variables in content
- **WHEN** content has no variable placeholders
- **THEN** the content SHALL be returned unchanged

#### Scenario: Missing context values
- **WHEN** content contains "${PROJECT_ID}" but project_id is None
- **THEN** "${PROJECT_ID}" SHALL be replaced with empty string

### Requirement: execute_inline returns substituted content as result
`execute_inline(skill, args, context)` SHALL substitute variables in the skill content and return a SkillResult with mode="inline" and output containing the substituted prompt text.

#### Scenario: Inline execution
- **GIVEN** a skill with content "Summarize this: $ARGUMENTS"
- **WHEN** execute_inline is called with args="the document"
- **THEN** SkillResult.output SHALL be "Summarize this: the document" and mode SHALL be "inline"

### Requirement: execute_fork runs an isolated sub-agent and returns output
`execute_fork(skill, args, context)` SHALL create an isolated agent using `create_agent` with the skill's tools and model_tier, run it to completion, extract the final output, and return a SkillResult with mode="fork".

#### Scenario: Fork execution success
- **GIVEN** a skill with context="fork", tools=["web_search"], content="Research $ARGUMENTS"
- **WHEN** execute_fork is called with args="Redis"
- **THEN** it SHALL call create_agent with the skill's tools and substituted content as task_description
- **AND** run_agent_to_completion SHALL execute the agent
- **AND** SkillResult.output SHALL contain the agent's final output text

#### Scenario: Fork execution inherits permission_mode
- **WHEN** execute_fork is called with parent context having permission_mode=STRICT
- **THEN** create_agent SHALL receive permission_mode=STRICT and parent_deny_rules

#### Scenario: Fork execution agent failure
- **WHEN** the forked agent exits with ERROR
- **THEN** SkillResult SHALL have mode="fork" and output containing the error information

### Requirement: SkillResult dataclass carries execution outcome
`SkillResult` SHALL be a dataclass with fields: mode (str: "inline"|"fork"), output (str), skill_name (str), success (bool, default True).

#### Scenario: Inline result
- **WHEN** SkillResult is created with mode="inline", output="prompt text", skill_name="summarize"
- **THEN** all fields SHALL be accessible

#### Scenario: Failed fork result
- **WHEN** SkillResult is created with mode="fork", success=False, output="error info"
- **THEN** success SHALL be False
