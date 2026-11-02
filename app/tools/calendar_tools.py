from __future__ import annotations

from typing import Any

from app.integrations.calendar_service import CalendarService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class GetCalendarEventsTool(Tool):
    name = "get_calendar_events"
    description = (
        "List calendar events, from now onward by default. Pass time_min/time_max "
        "(ISO 8601, e.g. 2026-08-10T00:00:00) to look at a specific day or range."
    )
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of events to return.",
            required=False,
        ),
        ToolParameter(name="time_min", type="string", description="Range start (ISO 8601).", required=False),
        ToolParameter(name="time_max", type="string", description="Range end (ISO 8601).", required=False),
    ]

    def __init__(self, calendar_service: CalendarService) -> None:
        self._service = calendar_service

    async def execute(
        self,
        max_results: int = 10,
        time_min: str | None = None,
        time_max: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        result = await self._service.list_upcoming_events(
            max_results=min(max_results, 100), time_min=time_min, time_max=time_max
        )
        if not result.success:
            return ToolResult(success=False, error=result.error)

        events = [
            {
                "id": e.id,
                "summary": e.summary,
                "start": e.start,
                "end": e.end,
                "location": e.location,
            }
            for e in result.events
        ]
        return ToolResult(success=True, result=events, metadata={"count": len(events)})


class CreateCalendarEventTool(Tool):
    name = "create_calendar_event"
    description = (
        "Create a calendar event. Requires user confirmation before it's created."
    )
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="summary", type="string", description="Event title."),
        ToolParameter(
            name="start",
            type="string",
            description="Start time in ISO 8601, e.g. 2026-08-10T14:00:00 (local time if no offset).",
        ),
        ToolParameter(
            name="end",
            type="string",
            description="End time in ISO 8601 (local time if no offset).",
        ),
        ToolParameter(
            name="location", type="string", description="Event location.", required=False
        ),
        ToolParameter(
            name="description", type="string", description="Event notes/description.", required=False
        ),
    ]

    def __init__(self, calendar_service: CalendarService) -> None:
        self._service = calendar_service

    async def describe(
        self, summary: str = "", start: str = "", end: str = "", **kwargs: Any
    ) -> str:
        return f"Create calendar event '{summary}' from {start} to {end}"

    async def execute(
        self,
        summary: str,
        start: str,
        end: str,
        location: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        result = await self._service.create_event(
            summary=summary, start=start, end=end, location=location, description=description
        )
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(
            success=True,
            result=f"Event '{result.event.summary}' created.",
            metadata={"id": result.event.id},
        )


class DeleteCalendarEventTool(Tool):
    name = "delete_calendar_event"
    description = "Delete a calendar event by its id. Requires user confirmation."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="event_id", type="string", description="Id of the event to delete."),
    ]

    def __init__(self, calendar_service: CalendarService) -> None:
        self._service = calendar_service

    async def describe(self, event_id: str | None = None, **kwargs: Any) -> str:
        if not event_id:
            return "Delete a calendar event (no id provided)"
        result = await self._service.get_event(event_id)
        if not result.success or result.event is None:
            return f"Delete calendar event {event_id} (details unavailable)"
        return f"Delete calendar event '{result.event.summary}' ({result.event.start})"

    async def execute(self, event_id: str, **kwargs: Any) -> ToolResult:
        result = await self._service.delete_event(event_id)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=f"Deleted calendar event {event_id}.")
