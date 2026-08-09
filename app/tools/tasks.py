from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.security.permissions import PermissionLevel
from app.storage.db import get_connection, init_schema
from app.tools.base import Tool, ToolParameter, ToolResult

VALID_PRIORITIES = {"low", "medium", "high"}


class CreateTaskTool(Tool):
    name = "create_task"
    description = "Create a task with an optional priority and due date."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="title", type="string", description="Short task title."),
        ToolParameter(
            name="priority",
            type="string",
            description="Task priority.",
            required=False,
            enum=sorted(VALID_PRIORITIES),
        ),
        ToolParameter(
            name="due_date",
            type="string",
            description="Due date in ISO format (YYYY-MM-DD), if any.",
            required=False,
        ),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    async def execute(
        self,
        title: str,
        priority: str | None = None,
        due_date: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not title or not title.strip():
            return ToolResult(success=False, error="Task title cannot be empty.")
        if priority is not None and priority not in VALID_PRIORITIES:
            return ToolResult(
                success=False,
                error=f"Invalid priority '{priority}'. Must be one of {sorted(VALID_PRIORITIES)}.",
            )

        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            created_at = datetime.now().isoformat()
            cursor = conn.execute(
                """
                INSERT INTO tasks (title, status, priority, due_date, created_at)
                VALUES (?, 'pending', ?, ?, ?)
                """,
                (title.strip(), priority, due_date, created_at),
            )
            conn.commit()
            return ToolResult(
                success=True,
                result=f"Task created (id={cursor.lastrowid}).",
                metadata={"id": cursor.lastrowid, "created_at": created_at},
            )
        finally:
            conn.close()


class ListTasksTool(Tool):
    name = "list_tasks"
    description = "List tasks, optionally filtered by status."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="status",
            type="string",
            description="Filter by status.",
            required=False,
            enum=["pending", "completed"],
        ),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    async def execute(self, status: str | None = None, **kwargs: Any) -> ToolResult:
        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY id DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
            tasks = [dict(row) for row in rows]
            return ToolResult(success=True, result=tasks, metadata={"count": len(tasks)})
        finally:
            conn.close()


class CompleteTaskTool(Tool):
    name = "complete_task"
    description = "Mark a task as completed."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="task_id", type="integer", description="Id of the task to complete."),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    async def execute(self, task_id: int, **kwargs: Any) -> ToolResult:
        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            completed_at = datetime.now().isoformat()
            cursor = conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ? AND status = 'pending'",
                (completed_at, task_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return ToolResult(
                    success=False,
                    error=f"No pending task found with id {task_id}.",
                )
            return ToolResult(success=True, result=f"Task #{task_id} marked complete.")
        finally:
            conn.close()


class DeleteTaskTool(Tool):
    name = "delete_task"
    description = "Delete a task by its id. Requires user confirmation."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="task_id", type="integer", description="Id of the task to delete."),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    def _get_title(self, task_id: int) -> str | None:
        conn = get_connection(self._db_path)
        try:
            init_schema(conn)
            row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return row["title"] if row else None
        finally:
            conn.close()

    async def describe(self, task_id: int | None = None, **kwargs: Any) -> str:
        if task_id is None:
            return "Delete a task (no id provided)"
        title = self._get_title(task_id)
        if title is None:
            return f"Delete task #{task_id} (not found)"
        return f'Delete task #{task_id}: "{title}"'

    async def execute(self, task_id: int, **kwargs: Any) -> ToolResult:
        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return ToolResult(success=False, error=f"No task found with id {task_id}.")
            return ToolResult(success=True, result=f"Deleted task #{task_id}.")
        finally:
            conn.close()
