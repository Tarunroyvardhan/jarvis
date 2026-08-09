from __future__ import annotations

from typing import Any

from app.integrations.dev_tools_service import DevToolsService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class GitStatusTool(Tool):
    name = "git_status"
    description = "Show git status for a project (read-only)."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="project_path", type="string", description="Path to the git repository."),
    ]

    def __init__(self, service: DevToolsService) -> None:
        self._service = service

    async def execute(self, project_path: str, **kwargs: Any) -> ToolResult:
        result = await self._service.git_status(project_path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.output)


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Show git diff for a project (read-only)."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="project_path", type="string", description="Path to the git repository."),
        ToolParameter(
            name="staged", type="boolean", description="Show staged changes instead of unstaged.", required=False
        ),
    ]

    def __init__(self, service: DevToolsService) -> None:
        self._service = service

    async def execute(self, project_path: str, staged: bool = False, **kwargs: Any) -> ToolResult:
        result = await self._service.git_diff(project_path, staged=staged)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.output or "(no changes)")


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the test suite for a project using its configured test command. "
        "Only works for projects with a test command configured."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="project_path", type="string", description="Path to the project."),
    ]

    def __init__(self, service: DevToolsService, project_test_commands: dict[str, list[str]]) -> None:
        self._service = service
        # project_path -> command argv, keyed by RESOLVED path, not the
        # raw string as configured. Previously this compared a resolved
        # lookup path against unresolved dict keys, which broke on
        # Windows: Path("/repo").resolve() becomes "C:\\repo", never
        # matching a key typed as "/repo" or even "D:\\repo" with
        # different casing/trailing-slash conventions. Resolving both
        # sides the same way at the same point makes the comparison
        # actually reliable across platforms.
        from pathlib import Path

        self._project_test_commands = {
            str(Path(path).resolve()): command for path, command in project_test_commands.items()
        }

    async def execute(self, project_path: str, **kwargs: Any) -> ToolResult:
        from pathlib import Path

        resolved = str(Path(project_path).resolve())
        command = self._project_test_commands.get(resolved)
        if command is None:
            return ToolResult(
                success=False,
                error=(
                    f"No test command configured for '{project_path}'. "
                    f"Configured projects: {list(self._project_test_commands.keys())}"
                ),
            )

        result = await self._service.run_tests(project_path, command)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.output)
