## ADDED Requirements

### Requirement: MemoryReadTool
The system SHALL provide a `MemoryReadTool` that allows agents to list and read memories.
- `name`: "memory_read"
- `input_schema`: `{"action": {"type": "string", "enum": ["list", "get"]}, "memory_id": {"type": "integer"}}`
  - `action` is required; `memory_id` is required when action="get"
- `is_concurrency_safe`: always `True`
- `is_read_only`: always `True`

#### Scenario: List memories
- **WHEN** `memory_read` is called with `{"action": "list"}`
- **THEN** it SHALL return `ToolResult(output=<formatted memory list with id, type, name, description>, success=True)`

#### Scenario: Get specific memory
- **WHEN** `memory_read` is called with `{"action": "get", "memory_id": 3}`
- **THEN** it SHALL return `ToolResult(output=<full memory content>, success=True)`

#### Scenario: Memory not found
- **WHEN** `memory_read` is called with `{"action": "get", "memory_id": 999}` and no such memory exists
- **THEN** it SHALL return `ToolResult(output="Error: memory not found: 999", success=False)`

#### Scenario: List with no memories
- **WHEN** `memory_read` is called with `{"action": "list"}` and the project has no memories
- **THEN** it SHALL return `ToolResult(output="No memories found for this project.", success=True)`

### Requirement: MemoryWriteTool
The system SHALL provide a `MemoryWriteTool` that allows agents to create, update, and delete memories.
- `name`: "memory_write"
- `input_schema`: `{"action": {"type": "string", "enum": ["write", "update", "delete"]}, "type": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}, "content": {"type": "string"}, "memory_id": {"type": "integer"}}`
  - `action` is required
  - For "write": `type`, `name`, `description`, `content` are required
  - For "update": `memory_id` is required, plus at least one of `name`, `description`, `content`
  - For "delete": `memory_id` is required
- `is_concurrency_safe`: always `False` (mutates state)
- `is_read_only`: always `False`

#### Scenario: Write new memory
- **WHEN** `memory_write` is called with `{"action": "write", "type": "fact", "name": "Project deadline", "description": "Timeline info", "content": "Deadline is 2026-05-01"}`
- **THEN** it SHALL create a new memory and return `ToolResult(output="Memory created: id=<id>, name='Project deadline'", success=True)`

#### Scenario: Update memory
- **WHEN** `memory_write` is called with `{"action": "update", "memory_id": 3, "content": "Updated content"}`
- **THEN** it SHALL update the memory and return `ToolResult(output="Memory updated: id=3", success=True)`

#### Scenario: Delete memory
- **WHEN** `memory_write` is called with `{"action": "delete", "memory_id": 3}`
- **THEN** it SHALL delete the memory and return `ToolResult(output="Memory deleted: id=3", success=True)`

#### Scenario: Write with invalid type
- **WHEN** `memory_write` is called with `{"action": "write", "type": "bogus", ...}`
- **THEN** it SHALL return `ToolResult(output="Error: invalid memory type 'bogus'. Valid: fact, preference, context, instruction", success=False)`

### Requirement: Memory tools access project_id from context
Both MemoryReadTool and MemoryWriteTool SHALL obtain `project_id` from `ToolContext.project_id` to scope all operations to the current project.

#### Scenario: Tool uses context project_id
- **WHEN** either memory tool is called with a ToolContext where `project_id=5`
- **THEN** all memory operations SHALL be scoped to project 5
