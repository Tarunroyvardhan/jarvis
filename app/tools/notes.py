from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.security.permissions import PermissionLevel
from app.storage.db import get_connection, init_schema
from app.tools.base import Tool, ToolParameter, ToolResult


class CreateNoteTool(Tool):
    name = "create_note"
    description = "Save a short note for later retrieval."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="content", type="string", description="The note text to save."),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    async def execute(self, content: str, **kwargs: Any) -> ToolResult:
        if not content or not content.strip():
            return ToolResult(success=False, error="Note content cannot be empty.")

        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            created_at = datetime.now().isoformat()
            cursor = conn.execute(
                "INSERT INTO notes (content, created_at) VALUES (?, ?)",
                (content.strip(), created_at),
            )
            conn.commit()
            return ToolResult(
                success=True,
                result=f"Note saved (id={cursor.lastrowid}).",
                metadata={"id": cursor.lastrowid, "created_at": created_at},
            )
        finally:
            conn.close()


class ListNotesTool(Tool):
    name = "list_notes"
    description = "List saved notes, most recent first."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of notes to return.",
            required=False,
        ),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    async def execute(self, limit: int = 10, **kwargs: Any) -> ToolResult:
        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            rows = conn.execute(
                "SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            notes = [dict(row) for row in rows]
            return ToolResult(success=True, result=notes, metadata={"count": len(notes)})
        finally:
            conn.close()


class DeleteNoteTool(Tool):
    name = "delete_note"
    description = "Delete a saved note by its id. Requires user confirmation."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="note_id", type="integer", description="Id of the note to delete."),
    ]

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    def _get_content(self, note_id: int) -> str | None:
        conn = get_connection(self._db_path)
        try:
            init_schema(conn)
            row = conn.execute("SELECT content FROM notes WHERE id = ?", (note_id,)).fetchone()
            return row["content"] if row else None
        finally:
            conn.close()

    async def describe(self, note_id: int | None = None, **kwargs: Any) -> str:
        if note_id is None:
            return "Delete a note (no id provided)"
        content = self._get_content(note_id)
        if content is None:
            return f"Delete note #{note_id} (not found)"
        preview = content if len(content) <= 60 else content[:57] + "..."
        return f'Delete note #{note_id}: "{preview}"'

    async def execute(self, note_id: int, **kwargs: Any) -> ToolResult:
        conn: sqlite3.Connection = get_connection(self._db_path)
        try:
            init_schema(conn)
            cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return ToolResult(success=False, error=f"No note found with id {note_id}.")
            return ToolResult(success=True, result=f"Deleted note #{note_id}.")
        finally:
            conn.close()
