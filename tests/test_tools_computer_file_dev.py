from unittest.mock import AsyncMock

import pytest

from app.integrations.computer_controller import ComputerActionResult
from app.integrations.dev_tools_service import DevToolsResult
from app.integrations.file_intelligence import FileEntry, FileResult
from app.security.permissions import PermissionLevel
from app.tools.computer_tools import OpenApplicationTool, OpenWebsiteTool
from app.tools.dev_tools import GitStatusTool, RunTestsTool
from app.tools.file_tools import DeleteFileTool, FindFilesTool


@pytest.mark.asyncio
async def test_open_application_tool_success():
    fake_controller = AsyncMock()
    fake_controller.open_application = lambda name: ComputerActionResult(success=True)

    tool = OpenApplicationTool(controller=fake_controller)
    result = await tool.execute(name="notepad")

    assert result.success is True


@pytest.mark.asyncio
async def test_open_application_tool_propagates_failure():
    fake_controller = AsyncMock()
    fake_controller.open_application = lambda name: ComputerActionResult(
        success=False, error="not allowed"
    )

    tool = OpenApplicationTool(controller=fake_controller)
    result = await tool.execute(name="unknown")

    assert result.success is False
    assert "not allowed" in result.error


@pytest.mark.asyncio
async def test_open_website_tool_is_low_risk_not_gated():
    fake_controller = AsyncMock()
    tool = OpenWebsiteTool(controller=fake_controller)
    assert tool.permission_level == PermissionLevel.LOW_RISK


@pytest.mark.asyncio
async def test_find_files_tool_formats_results():
    fake_service = AsyncMock()
    fake_service.find_files = lambda query, directory=None: FileResult(
        success=True,
        files=[FileEntry(path="/tmp/a.txt", name="a.txt", size_bytes=10, modified_at="now")],
    )

    tool = FindFilesTool(service=fake_service)
    result = await tool.execute(query="a")

    assert result.success is True
    assert result.result[0]["name"] == "a.txt"


@pytest.mark.asyncio
async def test_delete_file_tool_is_always_confirm():
    fake_service = AsyncMock()
    tool = DeleteFileTool(service=fake_service)
    assert tool.permission_level == PermissionLevel.ALWAYS_CONFIRM


@pytest.mark.asyncio
async def test_delete_file_tool_describe_shows_path():
    fake_service = AsyncMock()
    tool = DeleteFileTool(service=fake_service)

    description = await tool.describe(path="/tmp/important.txt")

    assert "/tmp/important.txt" in description
    assert "delete" in description.lower()


@pytest.mark.asyncio
async def test_delete_file_tool_execute():
    fake_service = AsyncMock()
    fake_service.delete_file = lambda path: FileResult(success=True, content=f"Deleted {path}")

    tool = DeleteFileTool(service=fake_service)
    result = await tool.execute(path="/tmp/gone.txt")

    assert result.success is True


@pytest.mark.asyncio
async def test_git_status_tool_read_only():
    fake_service = AsyncMock()
    tool = GitStatusTool(service=fake_service)
    assert tool.permission_level == PermissionLevel.READ_ONLY


@pytest.mark.asyncio
async def test_git_status_tool_returns_output():
    fake_service = AsyncMock()
    fake_service.git_status.return_value = DevToolsResult(success=True, output="clean")

    tool = GitStatusTool(service=fake_service)
    result = await tool.execute(project_path="/repo")

    assert result.success is True
    assert result.result == "clean"


@pytest.mark.asyncio
async def test_run_tests_tool_uses_configured_command_only(tmp_path):
    fake_service = AsyncMock()
    fake_service.run_tests.return_value = DevToolsResult(success=True, output="ok")

    repo_path = str(tmp_path)
    tool = RunTestsTool(
        service=fake_service, project_test_commands={repo_path: ["python", "-m", "pytest"]}
    )
    result = await tool.execute(project_path=repo_path)

    assert result.success is True
    fake_service.run_tests.assert_called_once()
    call_args = fake_service.run_tests.call_args
    assert call_args.args[1] == ["python", "-m", "pytest"] or call_args.kwargs.get(
        "test_command"
    ) == ["python", "-m", "pytest"]


@pytest.mark.asyncio
async def test_run_tests_tool_matches_differently_formatted_but_equivalent_path(tmp_path):
    """Regression test: the configured key and the path Claude passes in
    might be typed slightly differently (trailing slash, relative vs
    absolute, different case on Windows) but still refer to the same
    directory — resolution must make these match, not just literal
    string equality."""
    fake_service = AsyncMock()
    fake_service.run_tests.return_value = DevToolsResult(success=True, output="ok")

    # Configure with a trailing separator; call without one.
    configured_key = str(tmp_path) + "/"
    tool = RunTestsTool(
        service=fake_service, project_test_commands={configured_key: ["pytest"]}
    )

    result = await tool.execute(project_path=str(tmp_path))

    assert result.success is True


@pytest.mark.asyncio
async def test_run_tests_tool_rejects_unconfigured_project():
    fake_service = AsyncMock()

    tool = RunTestsTool(service=fake_service, project_test_commands={})
    result = await tool.execute(project_path="/some/random/repo")

    assert result.success is False
    assert "No test command configured" in result.error
    fake_service.run_tests.assert_not_called()
