## MODIFIED Requirements

### Requirement: MemoryWriteTool
The system SHALL provide a `MemoryWriteTool` that allows agents to create, update, and delete memories.
- `name`: "memory_write"
- `input_schema`: `{"action": {"type": "string", "enum": ["write", "update", "delete"]}, "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]}, "name": {"type": "string"}, "description": {"type": "string"}, "content": {"type": "string"}, "memory_id": {"type": "integer"}}`
  - `action` is required
  - For "write": `type`, `name`, `description`, `content` are required; `type` MUST be one of the four enum values
  - For "update": `memory_id` is required, plus at least one of `name`, `description`, `content`
  - For "delete": `memory_id` is required
- The `type` parameter's `description` in the tool schema SHALL explain the semantic meaning of each of the four values (user / feedback / project / reference) so the LLM can classify correctly without further context
- `is_concurrency_safe`: always `False` (mutates state)
- `is_read_only`: always `False`

#### Scenario: Write new memory
- **WHEN** `memory_write` is called with `{"action": "write", "type": "user", "name": "senior_dev", "description": "User is a senior developer", "content": "User is a senior developer — skip intro-level framing"}`
- **THEN** it SHALL create a new memory and return `ToolResult(output="Memory created: id=<id>, name='senior_dev'", success=True)`

#### Scenario: Update memory
- **WHEN** `memory_write` is called with `{"action": "update", "memory_id": 3, "content": "Updated content"}`
- **THEN** it SHALL update the memory and return `ToolResult(output="Memory updated: id=3", success=True)`

#### Scenario: Delete memory
- **WHEN** `memory_write` is called with `{"action": "delete", "memory_id": 3}`
- **THEN** it SHALL delete the memory and return `ToolResult(output="Memory deleted: id=3", success=True)`

#### Scenario: Write with invalid type
- **WHEN** `memory_write` is called with `{"action": "write", "type": "fact", ...}` (or any other value not in the enum)
- **THEN** it SHALL return `ToolResult(output="Error: invalid memory type 'fact'. Valid: user, feedback, project, reference", success=False)`
