## MODIFIED Requirements

### Requirement: System prompt is built in layers
`build_system_prompt(role_body, project_root, memory_context=None)` SHALL construct a system prompt by concatenating layers in order: identity, role, memory, skill placeholder. Each layer that returns None SHALL be skipped.

The `memory_context` parameter accepts an optional string of formatted memory content. When provided, the memory layer SHALL include it under a `# Memory` header.

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

#### Scenario: Skill layer is empty in Phase 3
- **WHEN** build_system_prompt is called in Phase 3
- **THEN** the skill layer SHALL contribute no content to the prompt

#### Scenario: Layers are separated by section headers
- **WHEN** build_system_prompt produces output with multiple layers
- **THEN** each layer SHALL be visually separated (e.g., markdown headers or blank lines)
