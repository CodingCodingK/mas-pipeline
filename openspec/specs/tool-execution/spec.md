## ADDED Requirements

### Requirement: Tool abstract base class
The system SHALL provide a `Tool` abstract base class with the following interface:
- `name: str` — unique tool identifier
- `description: str` — human/LLM-readable description
- `input_schema: dict` — JSON Schema defining accepted parameters
- `is_concurrency_safe(params: dict) -> bool` — whether this invocation can run concurrently
- `is_read_only(params: dict) -> bool` — whether this invocation is read-only (Phase 1: defaults to `is_concurrency_safe`)
- `async call(params: dict, context: ToolContext) -> ToolResult` — execute the tool

#### Scenario: Concrete tool implements all required methods
- **WHEN** a class inherits from `Tool` without implementing all abstract methods
- **THEN** Python raises `TypeError` at instantiation time

#### Scenario: Tool provides OpenAI function calling definition
- **WHEN** a Tool instance is registered
- **THEN** its `name`, `description`, and `input_schema` SHALL be exportable as `{"type": "function", "function": {"name", "description", "parameters"}}` format

### Requirement: ToolResult data structure
The system SHALL define a `ToolResult` dataclass with fields:
- `output: str` — text content returned to LLM
- `success: bool` (default `True`) — whether execution succeeded
- `metadata: dict` (default `{}`) — telemetry data not sent to LLM (e.g., exit_code, file_size)

#### Scenario: Successful tool execution
- **WHEN** a tool executes successfully
- **THEN** it SHALL return `ToolResult(output=<result text>, success=True)`

#### Scenario: Failed tool execution
- **WHEN** a tool execution fails (e.g., file not found, command error)
- **THEN** it SHALL return `ToolResult(output=<error message>, success=False)` instead of raising an exception

### Requirement: ToolContext data structure
The system SHALL define a `ToolContext` dataclass with fields:
- `agent_id: str`
- `run_id: str`
- `project_id: int | None`
- `abort_signal: asyncio.Event | None`

#### Scenario: Tool receives execution context
- **WHEN** Orchestrator calls `tool.call(params, context)`
- **THEN** context SHALL contain the current agent_id and run_id

### Requirement: Tool registry
The system SHALL provide a `ToolRegistry` class that supports:
- `register(tool: Tool)` — register a tool instance
- `get(name: str) -> Tool` — retrieve tool by name, raise `KeyError` if not found
- `list_definitions(names: list[str] | None = None) -> list[dict]` — export OpenAI function calling format, optionally filtered by name list

#### Scenario: Register and retrieve a tool
- **WHEN** a tool is registered with `registry.register(tool)`
- **THEN** `registry.get(tool.name)` SHALL return the same tool instance

#### Scenario: Duplicate registration rejected
- **WHEN** a tool is registered with a name that already exists
- **THEN** the system SHALL raise `ValueError`

#### Scenario: Export filtered tool definitions
- **WHEN** `list_definitions(names=["read_file"])` is called on a registry with multiple tools
- **THEN** only the definition for `read_file` SHALL be returned

### Requirement: Parameter cast before validation
The system SHALL provide a `cast_params(params, schema)` function that performs safe type coercion based on JSON Schema type declarations:
- `str` → `int` (e.g., "123" → 123)
- `str` → `float` (e.g., "3.14" → 3.14)
- `str` → `bool` (e.g., "true" → True)
- `float` → `int` when lossless (e.g., 3.0 → 3)
- `str` → `list` via JSON parse
- Non-convertible values SHALL be returned unchanged

#### Scenario: LLM passes number as string
- **WHEN** schema declares `{"timeout": {"type": "integer"}}` and LLM passes `{"timeout": "30"}`
- **THEN** `cast_params` SHALL convert to `{"timeout": 30}`

#### Scenario: Non-convertible value preserved
- **WHEN** schema declares `{"timeout": {"type": "integer"}}` and LLM passes `{"timeout": "abc"}`
- **THEN** `cast_params` SHALL return `{"timeout": "abc"}` unchanged for validate to catch

### Requirement: Parameter validation
The system SHALL provide a `validate_params(params, schema)` function that validates against JSON Schema and returns a list of error strings. An empty list means valid.

#### Scenario: Valid parameters
- **WHEN** params match the schema
- **THEN** `validate_params` SHALL return an empty list

#### Scenario: Invalid parameters
- **WHEN** params violate the schema (wrong type, missing required field)
- **THEN** `validate_params` SHALL return human-readable error strings describing each violation

### Requirement: Tool orchestrator dispatch
The system SHALL provide a `ToolOrchestrator` that dispatches a list of `ToolCallRequest` objects with the following strategy:
1. Partition tool calls into batches: consecutive `is_concurrency_safe=True` calls form one batch, each `is_concurrency_safe=False` call is its own batch
2. Execute batches in order: safe batches via `asyncio.gather` (max concurrency 10), unsafe batches serially
3. Return `list[ToolResult]` in the same order as the input tool calls

#### Scenario: All safe tools run concurrently
- **WHEN** Orchestrator receives `[Grep, Glob, ReadFile]` and all return `is_concurrency_safe=True`
- **THEN** all three SHALL execute concurrently in a single `asyncio.gather` batch

#### Scenario: Unsafe tool breaks batch
- **WHEN** Orchestrator receives `[Grep, Shell("rm -rf"), Grep]`
- **THEN** execution SHALL be: batch1=[Grep] concurrent → batch2=[Shell] serial → batch3=[Grep] concurrent

#### Scenario: Tool call with invalid parameters
- **WHEN** a tool call has parameters that fail validation (after cast)
- **THEN** Orchestrator SHALL return a `ToolResult(output=<error message>, success=False)` for that call without executing the tool

#### Scenario: Tool execution timeout or exception
- **WHEN** a tool's `call()` raises an exception or times out
- **THEN** Orchestrator SHALL catch it and return `ToolResult(output=<error description>, success=False)`
