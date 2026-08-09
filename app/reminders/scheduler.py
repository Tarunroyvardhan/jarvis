"""
ReminderScheduler — polls for due reminders while the app is running and
fires a notification callback for each.

This is intentionally NOT a real background service: it only runs while
`python -m jarvis` is running, as an asyncio task alongside the chat loop.
If the process isn't running when a reminder is due, it fires as soon as
the app next starts and calls check_once() — see `catch_up()`, used at
startup to report anything that was missed instead of silently dropping it.

`check_once()` is separated from the sleep loop specifically so it can be
unit tested without real waiting.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.reminders.models import Reminder
from app.reminders.repository import ReminderRepository

logger = logging.getLogger(__name__)

NotifyCallback = Callable[[Reminder], Awaitable[None]]

DEFAULT_POLL_INTERVAL_SECONDS = 30


class ReminderScheduler:
    def __init__(
        self,
        repository: ReminderRepository,
        notify: NotifyCallback,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._repo = repository
        self._notify = notify
        self._poll_interval = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def check_once(self, as_of: datetime | None = None) -> list[Reminder]:
        """Check for due reminders, fire notifications, and reschedule/complete
        each one. Returns the reminders that fired, for callers (like the
        startup catch-up notice) that want to report on them directly.
        """
        due = self._repo.get_due(as_of=as_of)
        fired: list[Reminder] = []
        for reminder in due:
            try:
                await self._notify(reminder)
            except Exception:  # noqa: BLE001 - a bad notify callback must not break the poll loop
                logger.exception("Reminder notify callback failed for reminder %s", reminder.id)
            self._repo.mark_fired(reminder.id)
            fired.append(reminder)
        return fired

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.check_once()
            except Exception:  # noqa: BLE001 - one bad poll should not kill the loop
                logger.exception("Reminder scheduler poll failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass  # normal: just means it's time to poll again

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None
