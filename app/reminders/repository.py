"""
ReminderRepository — SQLite-backed CRUD for reminders.

Recurrence handling lives here rather than in the scheduler: when a
recurring reminder fires, `mark_fired()` computes the next `trigger_at`
(today's occurrence + 1 day / + 1 week) and leaves it pending; a
one-time reminder is marked completed instead. The scheduler's only job
is to notice something is due and call this.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.reminders.models import Reminder, RecurrenceType, ReminderStatus
from app.storage.db import get_connection, init_schema

_RECURRENCE_DELTA = {
    RecurrenceType.DAILY: timedelta(days=1),
    RecurrenceType.WEEKLY: timedelta(weeks=1),
}


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        message=row["message"],
        trigger_at=datetime.fromisoformat(row["trigger_at"]),
        recurrence=RecurrenceType(row["recurrence"]),
        status=ReminderStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_fired_at=datetime.fromisoformat(row["last_fired_at"]) if row["last_fired_at"] else None,
    )


class ReminderRepository:
    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = get_connection(self._db_path)
        init_schema(conn)
        return conn

    def create(
        self,
        message: str,
        trigger_at: datetime,
        recurrence: RecurrenceType = RecurrenceType.NONE,
    ) -> Reminder:
        if not message or not message.strip():
            raise ValueError("Reminder message cannot be empty.")

        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """
                INSERT INTO reminders (message, trigger_at, recurrence, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (message.strip(), trigger_at.isoformat(), recurrence.value, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return _row_to_reminder(row)
        finally:
            conn.close()

    def list_active(self, limit: int = 50) -> list[Reminder]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' ORDER BY trigger_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_row_to_reminder(r) for r in rows]
        finally:
            conn.close()

    def get_due(self, as_of: datetime | None = None) -> list[Reminder]:
        as_of = as_of or datetime.now()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND trigger_at <= ? "
                "ORDER BY trigger_at ASC",
                (as_of.isoformat(),),
            ).fetchall()
            return [_row_to_reminder(r) for r in rows]
        finally:
            conn.close()

    def cancel(self, reminder_id: int) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (reminder_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_fired(self, reminder_id: int) -> Reminder | None:
        """Record that a reminder fired. Recurring reminders are rescheduled
        to their next occurrence and stay pending; one-time reminders are
        marked completed.
        """
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if row is None:
                return None
            reminder = _row_to_reminder(row)

            now = datetime.now()
            delta = _RECURRENCE_DELTA.get(reminder.recurrence)

            if delta is None:
                conn.execute(
                    "UPDATE reminders SET status = 'completed', last_fired_at = ? WHERE id = ?",
                    (now.isoformat(), reminder_id),
                )
            else:
                next_trigger = reminder.trigger_at + delta
                # If the app was offline for a while, don't fire a burst of
                # catch-up occurrences — just roll forward to the next one
                # that's actually still in the future.
                while next_trigger <= now:
                    next_trigger += delta
                conn.execute(
                    "UPDATE reminders SET trigger_at = ?, last_fired_at = ? WHERE id = ?",
                    (next_trigger.isoformat(), now.isoformat(), reminder_id),
                )

            conn.commit()
            updated_row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            return _row_to_reminder(updated_row)
        finally:
            conn.close()
