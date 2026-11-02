"""Tests for capabilities added in the overhaul: per-call permissions,
file writing, memory keyword search, reminder automations/timezones,
shell/process plumbing and speech cleanup."""

import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.file_intelligence import FileIntelligenceService
from app.integrations.system_control import run_process
from app.memory.models import MemoryType
from app.memory.repository import MemoryRepository
from app.reminders.repository import ReminderRepository
from app.security.path_guard import PathGuard
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolResult
from app.tools.file_tools import WriteFileTool
from app.tools.registry import ToolRegistry
from app.tools.system_tools import RunShellCommandTool
from app.voice.tts import clean_for_speech


class _Escalating(Tool):
    name = "escalating"
    description = "needs confirmation only for dangerous=True"
    permission_level = PermissionLevel.LOW_RISK
    parameters = []

    def permission_for(self, dangerous: bool = False, **kwargs):
        return PermissionLevel.CONFIRM_REQUIRED if dangerous else PermissionLevel.LOW_RISK

    async def execute(self, **kwargs):
        return ToolResult(success=True, result="ran")


@pytest.mark.asyncio
async def test_registry_honours_per_call_permission():
    registry = ToolRegistry()
    registry.register(_Escalating())

    assert (await registry.execute("escalating", None, dangerous=False)).success
    denied = await registry.execute("escalating", None, dangerous=True)
    assert denied.success is False
    assert "requires user confirmation" in denied.error


@pytest.mark.asyncio
async def test_registry_reports_bad_arguments_cleanly():
    class Strict(Tool):
        name = "strict"
        description = "d"
        permission_level = PermissionLevel.READ_ONLY
        parameters = []

        async def execute(self, required_arg: str):
            return ToolResult(success=True, result=required_arg)

    registry = ToolRegistry()
    registry.register(Strict())
    result = await registry.execute("strict", None)
    assert result.success is False
    assert "Invalid arguments" in result.error


@pytest.mark.asyncio
async def test_write_file_new_is_low_risk_overwrite_needs_confirmation(tmp_path):
    service = FileIntelligenceService(PathGuard([tmp_path]))
    tool = WriteFileTool(service)
    target = tmp_path / "notes" / "a.txt"

    assert tool.permission_for(path=str(target)) == PermissionLevel.LOW_RISK
    result = await tool.execute(path=str(target), content="hello")
    assert result.success and target.read_text() == "hello"

    assert tool.permission_for(path=str(target)) == PermissionLevel.CONFIRM_REQUIRED
    assert tool.permission_for(path=str(target), append=True) == PermissionLevel.LOW_RISK


def test_write_file_outside_allowed_root_is_refused(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    service = FileIntelligenceService(PathGuard([allowed]))
    result = service.write_file(str(tmp_path / "escape.txt"), "x")
    assert result.success is False
    assert not (tmp_path / "escape.txt").exists()


def test_move_and_copy_never_overwrite(tmp_path):
    service = FileIntelligenceService(PathGuard([tmp_path]))
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    assert service.copy_path(str(tmp_path / "a.txt"), str(tmp_path / "c.txt")).success
    assert service.move_path(str(tmp_path / "a.txt"), str(tmp_path / "b.txt")).success is False
    assert (tmp_path / "b.txt").read_text() == "b"


def test_file_walk_skips_dependency_folders(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "report.txt").write_text("x")
    (tmp_path / "report.txt").write_text("x")
    service = FileIntelligenceService(PathGuard([tmp_path]))

    result = service.find_files("report")

    assert [f.path for f in result.files] == [str(tmp_path / "report.txt")]


def test_memory_keyword_search_matches_any_word(tmp_path):
    repo = MemoryRepository(tmp_path / "m.db")
    repo.remember("Prefers dark roast coffee", MemoryType.PROFILE, permanent=True)
    repo.remember("Sister's birthday is in May", MemoryType.PROFILE, permanent=True)
    repo.remember("User: coffee chat log", MemoryType.CONVERSATION, permanent=False)

    found = repo.search("what coffee should I buy?", exclude_type=MemoryType.CONVERSATION)

    assert [m.content for m in found] == ["Prefers dark roast coffee"]
    assert repo.search("the and of") == []


def test_reminder_with_timezone_is_normalised_to_local(tmp_path):
    repo = ReminderRepository(tmp_path / "r.db")
    aware = datetime.now(timezone.utc) + timedelta(hours=1)

    reminder = repo.create("call mum", aware)

    assert reminder.trigger_at.tzinfo is None
    assert abs(reminder.trigger_at - (datetime.now() + timedelta(hours=1))) < timedelta(seconds=5)
    assert repo.get_due() == []
    assert len(repo.get_due(as_of=datetime.now() + timedelta(hours=2))) == 1


def test_reminder_task_prompt_round_trips(tmp_path):
    repo = ReminderRepository(tmp_path / "r.db")
    reminder = repo.create("Morning briefing", datetime.now(), task_prompt="Summarise the news")
    assert reminder.task_prompt == "Summarise the news"
    assert repo.list_active()[0].task_prompt == "Summarise the news"


@pytest.mark.asyncio
async def test_run_process_captures_output_and_exit_code():
    out = await run_process([sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"])
    assert out.exit_code == 3
    assert "hi" in out.stdout
    assert out.success is False


@pytest.mark.asyncio
async def test_run_process_timeout_kills_child():
    out = await run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert out.success is False
    assert "Timed out" in out.error


@pytest.mark.asyncio
async def test_shell_tool_always_requires_confirmation():
    tool = RunShellCommandTool()
    assert tool.permission_level == PermissionLevel.ALWAYS_CONFIRM
    description = await tool.describe(command="Get-Date", purpose="Check the clock")
    assert "Get-Date" in description and "Check the clock" in description

    registry = ToolRegistry()
    registry.register(tool)
    result = await registry.execute("run_shell_command", None, command="Get-Date")
    assert result.success is False  # no confirmation handler -> denied


def test_clean_for_speech_strips_markdown_and_links():
    text = "## Summary\n- **Bold** point\n- see [the docs](https://example.com) or https://x.y/z"
    assert clean_for_speech(text) == "Summary\nBold point\nsee the docs or"
