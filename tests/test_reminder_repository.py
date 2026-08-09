from datetime import datetime, timedelta

import pytest

from app.reminders.models import RecurrenceType, ReminderStatus
from app.reminders.repository import ReminderRepository


def test_create_reminder(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    when = datetime.now() + timedelta(minutes=20)

    reminder = repo.create("check the oven", when)

    assert reminder.message == "check the oven"
    assert reminder.status == ReminderStatus.PENDING
    assert reminder.recurrence == RecurrenceType.NONE


def test_create_rejects_empty_message(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    with pytest.raises(ValueError):
        repo.create("   ", datetime.now())


def test_list_active_only_returns_pending(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    r1 = repo.create("one", datetime.now() + timedelta(minutes=5))
    repo.create("two", datetime.now() + timedelta(minutes=10))
    repo.cancel(r1.id)

    active = repo.list_active()
    assert len(active) == 1
    assert active[0].message == "two"


def test_get_due_returns_only_past_or_present_reminders(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    past = repo.create("overdue", datetime.now() - timedelta(minutes=1))
    repo.create("future", datetime.now() + timedelta(hours=1))

    due = repo.get_due()
    assert len(due) == 1
    assert due[0].id == past.id


def test_cancel_marks_cancelled_and_removes_from_active(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    reminder = repo.create("one-off", datetime.now() + timedelta(minutes=5))

    assert repo.cancel(reminder.id) is True
    assert repo.list_active() == []


def test_cancel_nonexistent_returns_false(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    assert repo.cancel(9999) is False


def test_mark_fired_one_time_completes_it(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    reminder = repo.create("one-off", datetime.now() - timedelta(minutes=1))

    updated = repo.mark_fired(reminder.id)

    assert updated.status == ReminderStatus.COMPLETED
    assert repo.list_active() == []


def test_mark_fired_daily_reschedules_to_next_day(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    original_time = datetime.now() - timedelta(minutes=1)
    reminder = repo.create("standup", original_time, recurrence=RecurrenceType.DAILY)

    updated = repo.mark_fired(reminder.id)

    assert updated.status == ReminderStatus.PENDING
    assert updated.trigger_at > datetime.now()
    # roughly one day later than the original occurrence
    assert timedelta(hours=23) < (updated.trigger_at - original_time) < timedelta(hours=25)


def test_mark_fired_weekly_reschedules_to_next_week(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    original_time = datetime.now() - timedelta(minutes=1)
    reminder = repo.create("team sync", original_time, recurrence=RecurrenceType.WEEKLY)

    updated = repo.mark_fired(reminder.id)

    assert updated.status == ReminderStatus.PENDING
    delta = updated.trigger_at - original_time
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


def test_mark_fired_recurring_skips_multiple_missed_occurrences(tmp_path):
    """If the app was offline a long time, don't leave trigger_at in the past —
    it should roll forward to the next future occurrence, not just +1 interval."""
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    long_ago = datetime.now() - timedelta(days=10)
    reminder = repo.create("daily check", long_ago, recurrence=RecurrenceType.DAILY)

    updated = repo.mark_fired(reminder.id)

    assert updated.trigger_at > datetime.now()


def test_mark_fired_nonexistent_returns_none(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    assert repo.mark_fired(9999) is None
