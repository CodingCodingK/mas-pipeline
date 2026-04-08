## ADDED Requirements

### Requirement: TaskCreateTool lets LLM create planning tasks
`TaskCreateTool.call(params, context)` SHALL create a Task record with run_id automatically injected from ToolContext.

#### Scenario: Create a planning task
- **WHEN** task_create is called with subject="调研 Redis 架构" and description="深入调研..."
- **THEN** a Task SHALL be created with run_id from context, status='pending', and the tool SHALL return the task_id and subject

#### Scenario: Create a task with dependencies
- **WHEN** task_create is called with subject="撰写博客" and blocked_by=[7, 8]
- **THEN** a Task SHALL be created with blocked_by=[7, 8]

### Requirement: TaskCreateTool input schema
- `subject` (string, required): short description of the task
- `description` (string, optional): detailed description
- `blocked_by` (array of integers, optional): task IDs this task depends on

### Requirement: TaskUpdateTool lets LLM update task status
`TaskUpdateTool.call(params, context)` SHALL update a task's status to completed or failed.

#### Scenario: Complete a task
- **WHEN** task_update is called with task_id=7, status="completed", result="调研完成，发现..."
- **THEN** the task SHALL be updated via complete_task(7, result)

#### Scenario: Fail a task
- **WHEN** task_update is called with task_id=7, status="failed", result="调研失败，原因..."
- **THEN** the task SHALL be updated via fail_task(7, result)

#### Scenario: Invalid status
- **WHEN** task_update is called with status="running"
- **THEN** it SHALL return an error indicating only "completed" and "failed" are allowed

### Requirement: TaskUpdateTool input schema
- `task_id` (integer, required): ID of the task to update
- `status` (string, required, enum: completed/failed): new status
- `result` (string, required): output text or error message

### Requirement: TaskListTool shows all tasks for current run
`TaskListTool.call(params, context)` SHALL list all tasks for the current run (run_id from ToolContext).

#### Scenario: List tasks
- **WHEN** task_list is called
- **THEN** it SHALL return all tasks for the current run, each showing id, subject, status, owner

#### Scenario: No tasks exist
- **WHEN** task_list is called and no tasks exist for the run
- **THEN** it SHALL return "No tasks found"

### Requirement: TaskListTool input schema
No required parameters. run_id is injected from ToolContext.

### Requirement: TaskGetTool retrieves a single task with full details
`TaskGetTool.call(params, context)` SHALL return a single task's full details including result.

#### Scenario: Get completed task
- **WHEN** task_get is called with task_id=7 and the task is completed
- **THEN** it SHALL return id, subject, status, owner, result, blocked_by, created_at

#### Scenario: Get non-existent task
- **WHEN** task_get is called with a non-existent task_id
- **THEN** it SHALL return an error message

### Requirement: TaskGetTool input schema
- `task_id` (integer, required): ID of the task to retrieve
