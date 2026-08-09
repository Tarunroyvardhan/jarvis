"""
MemoryRepository — SQLite-backed CRUD for memories, with expiry rules.

Retention policy:
  * Auto-captured memories (conversation turns, episodic notes the
    assistant records on its own) are given an expires_at ~7 days out
    and get purged by `purge_expired()`.
  * Explicitly requested memories ("remember that...") are stored with
    expires_at=NULL and are permanent until removed via `forget()`.

Retrieval is deliberately simple: keyword LIKE matching plus
importance/recency ordering, no embeddings. This keeps the MVP honest
about what it actually needs. The interface is shaped so a future
vector-search implementation can slot in behind `retrieve()` without
callers changing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.memory.models import Memory, MemoryType
from app.storage.db import get_connection, init_schema

DEFAULT_AUTO_MEMORY_TTL_DAYS = 7


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        content=row["content"],
        type=MemoryType(row["type"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        importance=row["importance"],
        source=row["source"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
    )


class MemoryRepository:
    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = get_connection(self._db_path)
        init_schema(conn)
        return conn

    def remember(
        self,
        content: str,
        type: MemoryType,
        permanent: bool,
        importance: int = 1,
        source: str | None = None,
        metadata: dict | None = None,
        ttl_days: int = DEFAULT_AUTO_MEMORY_TTL_DAYS,
    ) -> Memory:
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        now = datetime.now()
        expires_at = None if permanent else now + timedelta(days=ttl_days)

        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO memories
                    (content, type, created_at, updated_at, importance, source, metadata, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content.strip(),
                    type.value,
                    now.isoformat(),
                    now.isoformat(),
                    importance,
                    source,
                    json.dumps(metadata or {}),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _row_to_memory(row)
        finally:
            conn.close()

    def retrieve(
        self,
        type: MemoryType | None = None,
        query: str | None = None,
        limit: int = 10,
        include_expired: bool = False,
    ) -> list[Memory]:
        conn = self._connect()
        try:
            clauses: list[str] = []
            params: list = []

            if type is not None:
                clauses.append("type = ?")
                params.append(type.value)
            if query:
                clauses.append("content LIKE ?")
                params.append(f"%{query}%")
            if not include_expired:
                clauses.append("(expires_at IS NULL OR expires_at > ?)")
                params.append(datetime.now().isoformat())

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = (
                f"SELECT * FROM memories {where} "
                "ORDER BY importance DESC, created_at DESC LIMIT ?"
            )
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [_row_to_memory(r) for r in rows]
        finally:
            conn.close()

    def update(self, memory_id: int, content: str) -> Memory | None:
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                (content.strip(), now, memory_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            return _row_to_memory(row)
        finally:
            conn.close()

    def forget(self, memory_id: int) -> bool:
        """Delete a memory by id. Returns True if something was actually deleted."""
        conn = self._connect()
        try:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def purge_expired(self) -> int:
        """Delete all memories past their expiry. Returns count deleted."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (datetime.now().isoformat(),),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
