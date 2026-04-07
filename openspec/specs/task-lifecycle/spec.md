## ADDED Requirements

### Requirement: create_task inserts a new task for a pipeline run
`create_task(run_id, subject, description, blocked_by)` SHALL insert a row into the `tasks` table with status='pending' and return a Task instance.

#### Scenario: Create task without dependencies
- **WHEN** create_task is called with an empty blocked_by list
- **THEN** a Task SHALL be created with status='pending' and blocked_by=[]

#### Scenario: Create task with dependencies
- **WHEN** create_task is called with blocked_by=[task_a_id, task_b_id]
- **THEN** a Task SHALL be created with the specified blocked_by array

### Requirement: claim_task atomically assigns a task to an agent
`claim_task(task_id, agent_id)` SHALL use SELECT FOR UPDATE to lock the row, verify status is 'pending', set status to 'in_progress' and owner to agent_id.

#### Scenario: Claim pending task
- **WHEN** claim_task is called on a task with status='pending'
- **THEN** status SHALL be set to 'in_progress', owner SHALL be set to agent_id, and updated_at SHALL be refreshed

#### Scenario: Claim non-pending task
- **WHEN** claim_task is called on a task with status != 'pending'
- **THEN** it SHALL raise an error indicating the task is already claimed or completed

### Requirement: complete_task marks a task as completed with result
`complete_task(task_id, result)` SHALL set status to 'completed', store the result text, and update updated_at.

#### Scenario: Complete an in-progress task
- **WHEN** complete_task is called on a task with status='in_progress'
- **THEN** status SHALL be 'completed', result SHALL contain the output text

### Requirement: fail_task marks a task as failed with error
`fail_task(task_id, error)` SHALL set status to 'failed', store the error in result, and update updated_at.

#### Scenario: Fail an in-progress task
- **WHEN** fail_task is called on a task with status='in_progress'
- **THEN** status SHALL be 'failed', result SHALL contain the error message

### Requirement: check_blocked reports whether a task's dependencies are satisfied
`check_blocked(task_id)` SHALL check if all tasks in the blocked_by array have status='completed'. Returns True if still blocked, False if all dependencies are met.

#### Scenario: All dependencies completed
- **WHEN** check_blocked is called and all tasks in blocked_by have status='completed'
- **THEN** it SHALL return False (not blocked)

#### Scenario: Some dependencies pending
- **WHEN** check_blocked is called and at least one task in blocked_by has status != 'completed'
- **THEN** it SHALL return True (still blocked)

#### Scenario: No dependencies
- **WHEN** check_blocked is called on a task with empty blocked_by
- **THEN** it SHALL return False (not blocked)

### Requirement: list_tasks and get_task provide query access
`list_tasks(run_id)` SHALL return all tasks for a run. `get_task(task_id)` SHALL return a single task or None.

#### Scenario: List tasks for a run
- **WHEN** list_tasks is called with a valid run_id
- **THEN** it SHALL return all tasks belonging to that run

#### Scenario: Get existing task
- **WHEN** get_task is called with a valid task_id
- **THEN** it SHALL return the Task instance

#### Scenario: Get non-existent task
- **WHEN** get_task is called with a non-existent task_id
- **THEN** it SHALL return None
