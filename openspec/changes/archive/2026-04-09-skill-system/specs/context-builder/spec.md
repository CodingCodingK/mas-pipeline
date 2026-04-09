## MODIFIED Requirements

### Requirement: System prompt is built in layers
`build_system_prompt(role_body, project_root, memory_context=None, skill_definitions=None)` SHALL construct a system prompt by concatenating layers in order: identity, role, memory, skill. Each layer that returns None SHALL be skipped.

The `memory_context` parameter accepts an optional string of formatted memory content. When provided, the memory layer SHALL include it under a `# Memory` header.

The `skill_definitions` parameter accepts an optional list of SkillDefinition objects. When provided, the skill layer SHALL include always-on skills' full content and on-demand skills' XML summaries.

#### Scenario: Identity layer includes platform info
- **WHEN** build_system_prompt is called
- **THEN** the identity layer SHALL include OS name, Python version, and project root path

#### Scenario: Role layer contains role file body
- **WHEN** build_system_prompt is called with role_body "You are a researcher."
- **THEN** the prompt SHALL contain "You are a researcher."

#### Scenario: Memory layer with content
- **WHEN** build_system_prompt is called with memory_context="User prefers dark mode.\nDeadline is May 1st."
- **THEN** the prompt SHALL contain a "# Memory" section with that content

#### Scenario: Memory layer without content
- **WHEN** build_system_prompt is called with memory_context=None
- **THEN** the memory layer SHALL contribute no content to the prompt

#### Scenario: Skill layer with always-on skill
- **WHEN** build_system_prompt is called with skill_definitions containing a skill with always=True and content="Always follow PEP8"
- **THEN** the skill layer SHALL include the full content "Always follow PEP8" under a section header

#### Scenario: Skill layer with on-demand skills
- **WHEN** build_system_prompt is called with skill_definitions containing skills with always=False
- **THEN** the skill layer SHALL include an XML summary with each skill's name, description, when_to_use, and arguments

#### Scenario: Skill layer with no skills
- **WHEN** build_system_prompt is called with skill_definitions=None or empty list
- **THEN** the skill layer SHALL contribute no content to the prompt

#### Scenario: Layers are separated by section headers
- **WHEN** build_system_prompt produces output with multiple layers
- **THEN** each layer SHALL be visually separated (e.g., markdown headers or blank lines)
