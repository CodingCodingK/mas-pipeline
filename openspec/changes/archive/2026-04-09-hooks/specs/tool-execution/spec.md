## MODIFIED Requirements

### Requirement: Tool orchestrator dispatch
The system SHALL provide a `ToolOrchestrator` that dispatches a list of `ToolCallRequest` objects with the following strategy:
1. Partition tool calls into batches: consecutive `is_concurrency_safe=True` calls form one batch, each `is_concurrency_safe=False` call is its own batch
2. Execute batches in order: safe batches via `asyncio.gather` (max concurrency 10), unsafe batches serially
3. For each tool call: run PreToolUse hooks before execution, run PostToolUse hooks on success or PostToolUseFailure hooks on failure
4. If PreToolUse hook returns deny, skip tool execution and return a ToolResult with the deny reason
5. If PreToolUse hook returns modify, use updated_input as the tool parameters
6. If PostToolUse hook returns additional_context, append it to the ToolResult output
7. Return `list[ToolResult]` in the same order as the input tool calls

#### Scenario: All safe tools run concurrently
- **WHEN** Orchestrator receives `[Grep, Glob, ReadFile]` and all return `is_concurrency_safe=True`
- **THEN** all three SHALL execute concurrently in a single `asyncio.gather` batch

#### Scenario: Unsafe tool breaks batch
- **WHEN** Orchestrator receives `[Grep, Shell("rm -rf"), Grep]`
- **THEN** execution SHALL be: batch1=[Grep] concurrent -> batch2=[Shell] serial -> batch3=[Grep] concurrent

#### Scenario: Tool call with invalid parameters
- **WHEN** a tool call has parameters that fail validation (after cast)
- **THEN** Orchestrator SHALL return a `ToolResult(output=<error message>, success=False)` for that call without executing the tool

#### Scenario: Tool execution timeout or exception
- **WHEN** a tool's `call()` raises an exception or times out
- **THEN** Orchestrator SHALL catch it and return `ToolResult(output=<error description>, success=False)`

#### Scenario: PreToolUse hook denies execution
- **WHEN** a PreToolUse hook returns action="deny" with reason="not allowed"
- **THEN** the tool SHALL NOT execute and ToolResult SHALL be ToolResult(output="Hook denied: not allowed", success=False)

#### Scenario: PreToolUse hook modifies input
- **WHEN** a PreToolUse hook returns action="modify" with updated_input={"command": "ls"}
- **THEN** the tool SHALL execute with the modified parameters

#### Scenario: PostToolUse hook adds context
- **WHEN** a PostToolUse hook returns additional_context="Security note: file was read from sensitive dir"
- **THEN** the ToolResult output SHALL have the additional context appended

#### Scenario: No HookRunner configured
- **WHEN** ToolOrchestrator has no HookRunner (None)
- **THEN** tool dispatch SHALL proceed identically to pre-hooks behavior
