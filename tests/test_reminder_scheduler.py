from datetime import datetime, timedelta

import pytest

from app.reminders.models import RecurrenceType, ReminderStatus
from app.reminders.repository import ReminderRepository
from app.reminders.scheduler import ReminderScheduler


@pytest.mark.asyncio
async def test_check_once_fires_due_reminder_and_notifies(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    repo.create("check the oven", datetime.now() - timedelta(minutes=1))

    notified = []

    async def notify(reminder):
        notified.append(reminder.message)

    scheduler = ReminderScheduler(repository=repo, notify=notify)
    fired = await scheduler.check_once()

    assert len(fired) == 1
    assert notified == ["check the oven"]
    assert repo.list_active() == []  # one-time reminder is now completed


@pytest.mark.asyncio
async def test_check_once_ignores_future_reminders(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    repo.create("not yet", datetime.now() + timedelta(hours=1))

    notified = []

    async def notify(reminder):
        notified.append(reminder.message)

    scheduler = ReminderScheduler(repository=repo, notify=notify)
    fired = await scheduler.check_once()

    assert fired == []
    assert notified == []
    assert len(repo.list_active()) == 1


@pytest.mark.asyncio
async def test_check_once_recurring_reminder_stays_active_after_firing(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    repo.create("standup", datetime.now() - timedelta(minutes=1), recurrence=RecurrenceType.DAILY)

    async def notify(reminder):
        pass

    scheduler = ReminderScheduler(repository=repo, notify=notify)
    fired = await scheduler.check_once()

    assert len(fired) == 1
    still_active = repo.list_active()
    assert len(still_active) == 1
    assert still_active[0].status == ReminderStatus.PENDING
    assert still_active[0].trigger_at > datetime.now()


@pytest.mark.asyncio
async def test_check_once_continues_despite_notify_exception(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    repo.create("will error", datetime.now() - timedelta(minutes=1))

    async def bad_notify(reminder):
        raise RuntimeError("notification channel down")

    scheduler = ReminderScheduler(repository=repo, notify=bad_notify)
    fired = await scheduler.check_once()

    # Still marked fired/completed even though the notify callback blew up —
    # a broken notifier shouldn't leave reminders stuck re-firing forever.
    assert len(fired) == 1
    assert repo.list_active() == []


@pytest.mark.asyncio
async def test_start_and_stop_scheduler_runs_cleanly(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")

    async def notify(reminder):
        pass

    scheduler = ReminderScheduler(repository=repo, notify=notify, poll_interval_seconds=60)
    scheduler.start()
    await scheduler.stop()  # should return promptly, not hang for 60s
