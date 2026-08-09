from datetime import datetime, timedelta

import pytest

from app.reminders.repository import ReminderRepository
from app.tools.reminder_tools import CancelReminderTool, CreateReminderTool, ListRemindersTool


@pytest.mark.asyncio
async def test_create_reminder_tool(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    tool = CreateReminderTool(repository=repo)
    when = (datetime.now() + timedelta(minutes=20)).isoformat()

    result = await tool.execute(message="check the oven", trigger_at=when)

    assert result.success is True
    assert len(repo.list_active()) == 1


@pytest.mark.asyncio
async def test_create_reminder_tool_rejects_bad_datetime(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    tool = CreateReminderTool(repository=repo)

    result = await tool.execute(message="x", trigger_at="not-a-date")

    assert result.success is False
    assert "Invalid trigger_at" in result.error


@pytest.mark.asyncio
async def test_create_reminder_tool_rejects_bad_recurrence(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    tool = CreateReminderTool(repository=repo)
    when = (datetime.now() + timedelta(minutes=20)).isoformat()

    result = await tool.execute(message="x", trigger_at=when, recurrence="fortnightly")

    assert result.success is False
    assert "Invalid recurrence" in result.error


@pytest.mark.asyncio
async def test_list_reminders_tool(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    repo.create("check the oven", datetime.now() + timedelta(minutes=20))
    tool = ListRemindersTool(repository=repo)

    result = await tool.execute()

    assert result.success is True
    assert len(result.result) == 1


@pytest.mark.asyncio
async def test_cancel_reminder_tool(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    reminder = repo.create("check the oven", datetime.now() + timedelta(minutes=20))
    tool = CancelReminderTool(repository=repo)

    result = await tool.execute(reminder_id=reminder.id)

    assert result.success is True
    assert repo.list_active() == []


@pytest.mark.asyncio
async def test_cancel_reminder_tool_nonexistent(tmp_path):
    repo = ReminderRepository(db_path=tmp_path / "test.db")
    tool = CancelReminderTool(repository=repo)

    result = await tool.execute(reminder_id=9999)

    assert result.success is False
