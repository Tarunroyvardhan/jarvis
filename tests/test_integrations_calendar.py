from unittest.mock import MagicMock

import pytest

from app.integrations.calendar_service import CalendarService


def _fake_resource(execute_return=None, execute_side_effect=None):
    """Mimics googleapiclient's fluent resource().events().list().execute()
    chain shape closely enough to exercise CalendarService's real call
    pattern without any network access or real credentials."""
    resource = MagicMock()
    execute_mock = MagicMock()
    if execute_side_effect is not None:
        execute_mock.side_effect = execute_side_effect
    else:
        execute_mock.return_value = execute_return
    resource.events.return_value.list.return_value.execute = execute_mock
    resource.events.return_value.get.return_value.execute = execute_mock
    resource.events.return_value.insert.return_value.execute = execute_mock
    resource.events.return_value.delete.return_value.execute = execute_mock
    return resource, execute_mock


@pytest.mark.asyncio
async def test_list_upcoming_events_parses_response():
    api_response = {
        "items": [
            {
                "id": "evt1",
                "summary": "Team sync",
                "start": {"dateTime": "2026-08-10T14:00:00-04:00"},
                "end": {"dateTime": "2026-08-10T15:00:00-04:00"},
                "location": "Zoom",
            }
        ]
    }
    resource, _ = _fake_resource(execute_return=api_response)
    service = CalendarService(resource)

    result = await service.list_upcoming_events()

    assert result.success is True
    assert len(result.events) == 1
    assert result.events[0].summary == "Team sync"
    assert result.events[0].location == "Zoom"


@pytest.mark.asyncio
async def test_list_upcoming_events_handles_empty_response():
    resource, _ = _fake_resource(execute_return={})
    service = CalendarService(resource)

    result = await service.list_upcoming_events()

    assert result.success is True
    assert result.events == []


@pytest.mark.asyncio
async def test_list_upcoming_events_missing_summary_gets_placeholder():
    api_response = {
        "items": [{"id": "evt1", "start": {"date": "2026-08-10"}, "end": {"date": "2026-08-11"}}]
    }
    resource, _ = _fake_resource(execute_return=api_response)
    service = CalendarService(resource)

    result = await service.list_upcoming_events()

    assert result.events[0].summary == "(no title)"
    assert result.events[0].start == "2026-08-10"  # all-day event uses date, not dateTime


@pytest.mark.asyncio
async def test_list_upcoming_events_reports_api_error():
    resource, _ = _fake_resource(execute_side_effect=RuntimeError("API quota exceeded"))
    service = CalendarService(resource)

    result = await service.list_upcoming_events()

    assert result.success is False
    assert "API quota exceeded" in result.error


@pytest.mark.asyncio
async def test_get_event_returns_single_event():
    api_response = {
        "id": "evt1",
        "summary": "Dentist",
        "start": {"dateTime": "2026-08-10T09:00:00-04:00"},
        "end": {"dateTime": "2026-08-10T10:00:00-04:00"},
    }
    resource, _ = _fake_resource(execute_return=api_response)
    service = CalendarService(resource)

    result = await service.get_event("evt1")

    assert result.success is True
    assert result.event.summary == "Dentist"


@pytest.mark.asyncio
async def test_create_event_rejects_empty_summary():
    resource, _ = _fake_resource()
    service = CalendarService(resource)

    result = await service.create_event(summary="   ", start="2026-08-10T09:00:00", end="2026-08-10T10:00:00")

    assert result.success is False
    assert "cannot be empty" in result.error


@pytest.mark.asyncio
async def test_create_event_success():
    api_response = {
        "id": "new_evt",
        "summary": "Lunch",
        "start": {"dateTime": "2026-08-10T12:00:00-04:00"},
        "end": {"dateTime": "2026-08-10T13:00:00-04:00"},
    }
    resource, _ = _fake_resource(execute_return=api_response)
    service = CalendarService(resource)

    result = await service.create_event(
        summary="Lunch", start="2026-08-10T12:00:00-04:00", end="2026-08-10T13:00:00-04:00"
    )

    assert result.success is True
    assert result.event.id == "new_evt"


@pytest.mark.asyncio
async def test_delete_event_success():
    resource, _ = _fake_resource(execute_return=None)
    service = CalendarService(resource)

    result = await service.delete_event("evt1")

    assert result.success is True


@pytest.mark.asyncio
async def test_delete_event_reports_error():
    resource, _ = _fake_resource(execute_side_effect=RuntimeError("event not found"))
    service = CalendarService(resource)

    result = await service.delete_event("nonexistent")

    assert result.success is False
    assert "event not found" in result.error
