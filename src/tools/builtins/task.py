"""Built-in tools: task_create / task_update / task_list / task_get — LLM-facing task management."""

from __future__ import annotations

from src.tools.base import Tool, ToolContext, ToolResult


class TaskCreateTool(Tool):
    name = "task_create"
    description = (
        "Create a planning task. Use this to break down work into trackable sub-tasks. "
        "run_id is automatically injected — you don't need to provide it."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Short description of the task.",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what needs to be done.",
            },
            "blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs that must complete before this task can start.",
            },
        },
        "required": ["subject"],
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.task.manager import create_task
        from src.tools.builtins.spawn_agent import SpawnAgentTool

        # Resolve run_id (int) from context
        run_id_int = await SpawnAgentTool()._resolve_run_id(context)

        task = await create_task(
            run_id=run_id_int,
            subject=params["subject"],
            description=params.get("description"),
            blocked_by=params.get("blocked_by"),
        )
        return ToolResult(
            output=f"Task created: id={task.id}, subject='{task.subject}'",
            metadata={"task_id": task.id},
        )


class TaskUpdateTool(Tool):
    name = "task_update"
    description = (
        "Update a task's status to 'completed' or 'failed' with a result message."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to update.",
            },
            "status": {
                "type": "string",
                "enum": ["completed", "failed"],
                "description": "New status: 'completed' or 'failed'.",
            },
            "result": {
                "type": "string",
                "description": "Output text (if completed) or error message (if failed).",
            },
        },
        "required": ["task_id", "status", "result"],
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.task.manager import complete_task, fail_task

        task_id: int = params["task_id"]
        status: str = params["status"]
        result_text: str = params["result"]

        if status == "completed":
            task = await complete_task(task_id, result_text)
        elif status == "failed":
            task = await fail_task(task_id, result_text)
        else:
            return ToolResult(
                output=f"Error: status must be 'completed' or 'failed', got '{status}'",
                success=False,
            )

        return ToolResult(
            output=f"Task {task_id} updated: status='{task.status}'",
        )


class TaskListTool(Tool):
    name = "task_list"
    description = (
        "List all tasks for the current run. Shows id, subject, status, and owner."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {},
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.task.manager import list_tasks
        from src.tools.builtins.spawn_agent import SpawnAgentTool

        run_id_int = await SpawnAgentTool()._resolve_run_id(context)
        tasks = await list_tasks(run_id_int)

        if not tasks:
            return ToolResult(output="No tasks found for this run.")

        lines = []
        for t in tasks:
            blocked = f" blocked_by={t.blocked_by}" if t.blocked_by else ""
            lines.append(
                f"  id={t.id} | {t.status:<12} | owner={t.owner or '-'} | {t.subject}{blocked}"
            )
        return ToolResult(output="Tasks:\n" + "\n".join(lines))


class TaskGetTool(Tool):
    name = "task_get"
    description = (
        "Get full details of a single task, including its result."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to retrieve.",
            },
        },
        "required": ["task_id"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.task.manager import get_task

        task_id: int = params["task_id"]
        task = await get_task(task_id)

        if task is None:
            return ToolResult(
                output=f"Error: task {task_id} not found",
                success=False,
            )

        lines = [
            f"id: {task.id}",
            f"subject: {task.subject}",
            f"status: {task.status}",
            f"owner: {task.owner or '-'}",
            f"blocked_by: {task.blocked_by or []}",
            f"created_at: {task.created_at}",
        ]
        if task.description:
            lines.append(f"description: {task.description}")
        if task.result:
            lines.append(f"result: {task.result}")

        return ToolResult(output="\n".join(lines))
