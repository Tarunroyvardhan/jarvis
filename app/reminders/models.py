"""Data model for reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class RecurrenceType(str, Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Reminder:
    id: int
    message: str
    trigger_at: datetime
    recurrence: RecurrenceType
    status: ReminderStatus
    created_at: datetime
    last_fired_at: datetime | None = None
