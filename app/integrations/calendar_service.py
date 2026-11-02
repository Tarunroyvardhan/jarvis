"""
Google Calendar integration.

CalendarService takes an already-built Calendar API resource object (see
google_auth.build_calendar_resource) rather than constructing one itself
— this is what makes it testable with a fake resource that mimics the
same call shape, without needing real credentials or network access.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str
    start: str
    end: str
    location: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class CalendarResult:
    success: bool
    events: list[CalendarEvent] = field(default_factory=list)
    event: CalendarEvent | None = None
    error: str | None = None


def _parse_event(item: dict) -> CalendarEvent:
    start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
    end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", "")
    return CalendarEvent(
        id=item.get("id", ""),
        summary=item.get("summary") or "(no title)",
        start=start,
        end=end,
        location=item.get("location"),
        description=item.get("description"),
    )


def _to_rfc3339(value: str) -> str:
    """Google requires a timezone offset on timeMin/timeMax. Accept plain
    dates and naive datetimes (interpreted as local time) as well."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # assume local time
    return parsed.isoformat()


def _with_local_offset(value: str) -> str:
    """Event start/end without an offset would be rejected by the API
    (no timeZone given), so treat them as local time."""
    try:
        return _to_rfc3339(value)
    except ValueError:
        return value


class CalendarService:
    def __init__(self, resource) -> None:
        self._resource = resource

    async def list_upcoming_events(
        self, max_results: int = 10, time_min: str | None = None, time_max: str | None = None
    ) -> CalendarResult:
        try:
            params = {
                "calendarId": "primary",
                "timeMin": _to_rfc3339(time_min) if time_min else datetime.now(timezone.utc).isoformat(),
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if time_max:
                params["timeMax"] = _to_rfc3339(time_max)
        except ValueError as exc:
            return CalendarResult(success=False, error=f"Invalid date/time: {exc}")
        try:
            response = await asyncio.to_thread(
                lambda: self._resource.events().list(**params).execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to list calendar events")
            return CalendarResult(success=False, error=str(exc))

        events = [_parse_event(item) for item in response.get("items", [])]
        return CalendarResult(success=True, events=events)

    async def get_event(self, event_id: str) -> CalendarResult:
        try:
            item = await asyncio.to_thread(
                lambda: self._resource.events()
                .get(calendarId="primary", eventId=event_id)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return CalendarResult(success=False, error=str(exc))
        return CalendarResult(success=True, event=_parse_event(item))

    async def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str | None = None,
        location: str | None = None,
    ) -> CalendarResult:
        if not summary or not summary.strip():
            return CalendarResult(success=False, error="Event summary cannot be empty.")

        body: dict = {
            "summary": summary.strip(),
            "start": {"dateTime": _with_local_offset(start)},
            "end": {"dateTime": _with_local_offset(end)},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location

        try:
            created = await asyncio.to_thread(
                lambda: self._resource.events()
                .insert(calendarId="primary", body=body)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to create calendar event")
            return CalendarResult(success=False, error=str(exc))

        return CalendarResult(success=True, event=_parse_event(created))

    async def delete_event(self, event_id: str) -> CalendarResult:
        try:
            await asyncio.to_thread(
                lambda: self._resource.events()
                .delete(calendarId="primary", eventId=event_id)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to delete calendar event")
            return CalendarResult(success=False, error=str(exc))
        return CalendarResult(success=True)
