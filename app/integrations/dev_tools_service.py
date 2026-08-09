"""
Developer tools — git status/diff (strictly read-only) and running tests
via a fixed, configured command per project. Deliberately does NOT
implement git push, force-push, merge, branch deletion, or anything that
touches a remote — that's not gated behind a permission level, it simply
doesn't exist as a callable operation, per the design doc's explicit
prohibition.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from app.security.path_guard import PathAccessError, PathGuard

logger = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class DevToolsResult:
    success: bool
    output: str = ""
    error: str | None = None


class DevToolsService:
    def __init__(self, path_guard: PathGuard) -> None:
        self._guard = path_guard

    def _resolve_project(self, project_path: str) -> Path:
        resolved = self._guard.resolve(project_path, must_exist=True)
        if not resolved.is_dir():
            raise PathAccessError(f"'{resolved}' is not a directory.")
        if not (resolved / ".git").exists():
            raise PathAccessError(f"'{resolved}' is not a git repository.")
        return resolved

    async def _run(self, args: list[str], cwd: Path) -> DevToolsResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            return DevToolsResult(
                success=False, error=f"Command timed out after {SUBPROCESS_TIMEOUT_SECONDS}s."
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Command failed: %s", args)
            return DevToolsResult(success=False, error=str(exc))

        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")

        if process.returncode != 0 and not output.strip():
            return DevToolsResult(
                success=False, error=error_output or f"Command exited with code {process.returncode}"
            )

        return DevToolsResult(success=True, output=output or error_output)

    async def git_status(self, project_path: str) -> DevToolsResult:
        try:
            repo = self._resolve_project(project_path)
        except PathAccessError as exc:
            return DevToolsResult(success=False, error=str(exc))
        return await self._run(["git", "status", "--short", "--branch"], cwd=repo)

    async def git_diff(self, project_path: str, staged: bool = False) -> DevToolsResult:
        try:
            repo = self._resolve_project(project_path)
        except PathAccessError as exc:
            return DevToolsResult(success=False, error=str(exc))
        args = ["git", "diff"] + (["--staged"] if staged else [])
        return await self._run(args, cwd=repo)

    async def run_tests(self, project_path: str, test_command: list[str]) -> DevToolsResult:
        try:
            repo = self._resolve_project(project_path)
        except PathAccessError as exc:
            return DevToolsResult(success=False, error=str(exc))

        if not test_command:
            return DevToolsResult(success=False, error="No test command configured for this project.")

        return await self._run(test_command, cwd=repo)
