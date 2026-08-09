from unittest.mock import AsyncMock

import pytest

from app.integrations.calendar_service import CalendarEvent, CalendarResult
from app.tools.calendar_tools import (
    CreateCalendarEventTool,
    DeleteCalendarEventTool,
    GetCalendarEventsTool,
)


@pytest.mark.asyncio
async def test_get_calendar_events_tool_formats_events():
    fake_service = AsyncMock()
    fake_service.list_upcoming_events.return_value = CalendarResult(
        success=True,
        events=[
            CalendarEvent(id="1", summary="Standup", start="2026-08-10T09:00:00", end="2026-08-10T09:30:00")
        ],
    )

    tool = GetCalendarEventsTool(calendar_service=fake_service)
    result = await tool.execute()

    assert result.success is True
    assert result.result[0]["summary"] == "Standup"


@pytest.mark.asyncio
async def test_get_calendar_events_tool_propagates_error():
    fake_service = AsyncMock()
    fake_service.list_upcoming_events.return_value = CalendarResult(
        success=False, error="API unavailable"
    )

    tool = GetCalendarEventsTool(calendar_service=fake_service)
    result = await tool.execute()

    assert result.success is False
    assert "API unavailable" in result.error


@pytest.mark.asyncio
async def test_create_calendar_event_describe_shows_details():
    fake_service = AsyncMock()
    tool = CreateCalendarEventTool(calendar_service=fake_service)

    description = await tool.describe(
        summary="Dentist appointment", start="2026-08-10T09:00:00", end="2026-08-10T10:00:00"
    )

    assert "Dentist appointment" in description
    assert "2026-08-10T09:00:00" in description


@pytest.mark.asyncio
async def test_create_calendar_event_tool_success():
    fake_service = AsyncMock()
    fake_service.create_event.return_value = CalendarResult(
        success=True,
        event=CalendarEvent(id="new1", summary="Lunch", start="x", end="y"),
    )

    tool = CreateCalendarEventTool(calendar_service=fake_service)
    result = await tool.execute(summary="Lunch", start="2026-08-10T12:00:00", end="2026-08-10T13:00:00")

    assert result.success is True
    assert result.metadata["id"] == "new1"


@pytest.mark.asyncio
async def test_delete_calendar_event_describe_fetches_event_details():
    fake_service = AsyncMock()
    fake_service.get_event.return_value = CalendarResult(
        success=True,
        event=CalendarEvent(id="evt1", summary="Team sync", start="2026-08-10T14:00:00", end="2026-08-10T15:00:00"),
    )

    tool = DeleteCalendarEventTool(calendar_service=fake_service)
    description = await tool.describe(event_id="evt1")

    assert "Team sync" in description
    assert "2026-08-10T14:00:00" in description


@pytest.mark.asyncio
async def test_delete_calendar_event_describe_handles_lookup_failure_gracefully():
    fake_service = AsyncMock()
    fake_service.get_event.return_value = CalendarResult(success=False, error="not found")

    tool = DeleteCalendarEventTool(calendar_service=fake_service)
    description = await tool.describe(event_id="evt1")

    assert "evt1" in description
    assert "details unavailable" in description


@pytest.mark.asyncio
async def test_delete_calendar_event_tool_success():
    fake_service = AsyncMock()
    fake_service.delete_event.return_value = CalendarResult(success=True)

    tool = DeleteCalendarEventTool(calendar_service=fake_service)
    result = await tool.execute(event_id="evt1")

    assert result.success is True
