"""
Reminder tools exposed to Claude.

As with memory tools, Claude decides when and how to call these from
understanding the request (e.g. computing an absolute trigger_at from
"remind me in 20 minutes" or "every Monday at 9am") — there's no phrase
parser here. These classes only implement what happens once Claude has
already made that call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.reminders.models import RecurrenceType
from app.reminders.repository import ReminderRepository
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult

_RECURRENCE_CHOICES = [r.value for r in RecurrenceType]


class CreateReminderTool(Tool):
    name = "create_reminder"
    description = (
        "Create a reminder. Compute trigger_at yourself as an absolute "
        "ISO 8601 datetime (YYYY-MM-DDTHH:MM:SS) based on the user's request "
        "and the current time — e.g. 'in 20 minutes' or 'tomorrow at 8pm'. "
        "Use recurrence='daily' or 'weekly' for recurring reminders; "
        "trigger_at is then the first occurrence."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="message", type="string", description="What to remind the user about."),
        ToolParameter(
            name="trigger_at",
            type="string",
            description="Absolute ISO 8601 datetime for when this should fire.",
        ),
        ToolParameter(
            name="recurrence",
            type="string",
            description="Recurrence pattern.",
            required=False,
            enum=_RECURRENCE_CHOICES,
        ),
    ]

    def __init__(self, repository: ReminderRepository) -> None:
        self._repo = repository

    async def execute(
        self,
        message: str,
        trigger_at: str,
        recurrence: str = "none",
        **kwargs: Any,
    ) -> ToolResult:
        try:
            when = datetime.fromisoformat(trigger_at)
        except ValueError:
            return ToolResult(
                success=False,
                error=f"Invalid trigger_at '{trigger_at}'; expected ISO 8601 format.",
            )

        try:
            recurrence_type = RecurrenceType(recurrence)
        except ValueError:
            return ToolResult(success=False, error=f"Invalid recurrence: '{recurrence}'")

        try:
            reminder = self._repo.create(message=message, trigger_at=when, recurrence=recurrence_type)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            result=f"Reminder set (id={reminder.id}) for {reminder.trigger_at.isoformat()}.",
            metadata={"id": reminder.id},
        )


class ListRemindersTool(Tool):
    name = "list_reminders"
    description = "List active (pending) reminders, soonest first."
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    def __init__(self, repository: ReminderRepository) -> None:
        self._repo = repository

    async def execute(self, **kwargs: Any) -> ToolResult:
        reminders = self._repo.list_active()
        results = [
            {
                "id": r.id,
                "message": r.message,
                "trigger_at": r.trigger_at.isoformat(),
                "recurrence": r.recurrence.value,
            }
            for r in reminders
        ]
        return ToolResult(success=True, result=results, metadata={"count": len(results)})


class CancelReminderTool(Tool):
    name = "cancel_reminder"
    description = "Cancel a pending reminder by its id."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="reminder_id", type="integer", description="Id of the reminder to cancel."),
    ]

    def __init__(self, repository: ReminderRepository) -> None:
        self._repo = repository

    async def execute(self, reminder_id: int, **kwargs: Any) -> ToolResult:
        cancelled = self._repo.cancel(reminder_id)
        if cancelled:
            return ToolResult(success=True, result=f"Cancelled reminder {reminder_id}.")
        return ToolResult(
            success=False, error=f"No pending reminder found with id {reminder_id}."
        )
