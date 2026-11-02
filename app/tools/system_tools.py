"""
System-access tools: shell, status, processes, screen, clipboard, media,
lock screen, notifications.

run_shell_command is the most powerful tool Jarvis has, so it is Level 3:
the exact command and working directory are shown to the user, and
nothing runs without a typed "yes" (automated runs, which have no one to
ask, are always refused).
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from app.integrations import system_control as sc
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


_START_PROCESS = re.compile(
    r"""^\s*(?:Start-Process|start)\s+(?:-FilePath\s+)?(?P<q>["']?)(?P<path>[^"';&|`$()<>\r\n]+?)(?P=q)\s*;?\s*$""",
    re.IGNORECASE,
)


def _is_installed_app_launch(command: str) -> bool:
    """True only for exactly `Start-Process "<path>"` where <path> is the
    program Windows itself registers for that app name (e.g. Chrome in
    Program Files) — no arguments, pipes, variables or extra commands."""
    match = _START_PROCESS.match(command or "")
    if not match or sys.platform != "win32":
        return False
    path = Path(match.group("path").strip())
    if path.suffix.lower() != ".exe" or not path.is_absolute():
        return False
    try:
        from app.integrations.app_finder import find_windows_app

        registered = find_windows_app(path.stem)
        return bool(registered) and Path(registered).resolve() == path.resolve()
    except Exception:  # noqa: BLE001 - when unsure, ask
        return False


class RunShellCommandTool(Tool):
    name = "run_shell_command"
    description = (
        "Run a PowerShell command on the user's computer and return its output. "
        "The user sees the exact command and must approve it first. Use for "
        "anything without a dedicated tool: installing software (winget), "
        "system settings, scripts, network checks, file operations outside "
        "allowed folders. Commands must be non-interactive (no prompts)."
    )
    permission_level = PermissionLevel.ALWAYS_CONFIRM
    parameters = [
        ToolParameter(name="command", type="string", description="The PowerShell command to run."),
        ToolParameter(
            name="working_directory",
            type="string",
            description="Folder to run the command in (optional).",
            required=False,
        ),
        ToolParameter(
            name="timeout_seconds",
            type="integer",
            description="Maximum run time before the command is stopped (default 120, max 1800).",
            required=False,
        ),
        ToolParameter(
            name="purpose",
            type="string",
            description="One short sentence telling the user what this command does and why.",
            required=False,
        ),
    ]

    def __init__(self, default_timeout: int = 120) -> None:
        self._default_timeout = default_timeout

    def permission_for(self, command: str = "", **kwargs: Any) -> PermissionLevel:
        # Starting an installed app is no riskier than open_application, so
        # don't make the user approve it just because the model went via the
        # shell. Anything else — even one extra character — still asks.
        if _is_installed_app_launch(command):
            return PermissionLevel.LOW_RISK
        return PermissionLevel.ALWAYS_CONFIRM

    async def describe(
        self, command: str = "", working_directory: str | None = None, purpose: str | None = None, **kwargs: Any
    ) -> str:
        lines = []
        if purpose:
            lines.append(purpose)
        lines.append(f"Run PowerShell command{f' in {working_directory}' if working_directory else ''}:")
        lines.append(f"    {command}")
        return "\n".join(lines)

    async def execute(
        self,
        command: str,
        working_directory: str | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not command or not command.strip():
            return ToolResult(success=False, error="Empty command.")
        timeout = max(5, min(int(timeout_seconds or self._default_timeout), 1800))
        out = await sc.run_shell(command, cwd=working_directory, timeout=timeout)
        if out.error:
            return ToolResult(success=False, error=out.error)
        # A non-zero exit is still useful information for the model, so it
        # is reported as a failed result *with* the output attached.
        if not out.success:
            return ToolResult(success=False, error=out.as_text())
        return ToolResult(success=True, result=out.as_text())


class GetSystemInfoTool(Tool):
    name = "get_system_info"
    description = (
        "Get the computer's current status: OS, CPU load, memory, disk space, "
        "battery, uptime and the biggest running processes."
    )
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            info = await asyncio.to_thread(sc.system_info)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Could not read system info: {exc}")
        return ToolResult(success=True, result=info)


class ListProcessesTool(Tool):
    name = "list_processes"
    description = "List running processes (largest memory users first), optionally filtered by name."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="name_filter", type="string", description="Only processes whose name contains this.", required=False),
        ToolParameter(name="limit", type="integer", description="Maximum results (default 25).", required=False),
    ]

    async def execute(self, name_filter: str | None = None, limit: int = 25, **kwargs: Any) -> ToolResult:
        try:
            procs = await asyncio.to_thread(sc.list_processes, name_filter, min(limit, 200))
        except ImportError:
            return ToolResult(success=False, error="psutil is not installed. Install with: pip install -e \".[system]\"")
        rows = [{"pid": p["pid"], "name": p["name"], "memory": sc._fmt_bytes(p["memory"])} for p in procs]
        return ToolResult(success=True, result=rows or "No matching processes.")


class KillProcessTool(Tool):
    name = "kill_process"
    description = "Stop a running process by its pid (get it from list_processes). Requires user confirmation."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="pid", type="integer", description="Process id to stop."),
    ]

    async def describe(self, pid: int | None = None, **kwargs: Any) -> str:
        name = sc.process_name(pid) if pid is not None else None
        return f"Stop process {name or '(unknown)'} (pid {pid})"

    async def execute(self, pid: int, **kwargs: Any) -> ToolResult:
        try:
            message = await asyncio.to_thread(sc.terminate_process, int(pid))
        except ImportError:
            return ToolResult(success=False, error="psutil is not installed. Install with: pip install -e \".[system]\"")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Could not stop pid {pid}: {exc}")
        return ToolResult(success=True, result=message)


class TakeScreenshotTool(Tool):
    name = "take_screenshot"
    description = (
        "Capture the user's screen and look at it. Use when the user asks about "
        "what's on their screen, or to check the result of an action."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            block, note = await asyncio.to_thread(sc.capture_screenshot)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Screenshot failed: {exc}")
        return ToolResult(success=True, result=note, content_blocks=[block])


class GetClipboardTool(Tool):
    name = "get_clipboard"
    description = "Read the text currently on the clipboard."
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            text = await sc.get_clipboard()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Could not read clipboard: {exc}")
        return ToolResult(success=True, result=text or "(clipboard is empty)")


class SetClipboardTool(Tool):
    name = "set_clipboard"
    description = "Put text on the clipboard so the user can paste it."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="text", type="string", description="Text to copy."),
    ]

    async def execute(self, text: str, **kwargs: Any) -> ToolResult:
        try:
            await sc.set_clipboard(text)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Could not set clipboard: {exc}")
        return ToolResult(success=True, result=f"Copied {len(text)} characters to the clipboard.")


class MediaControlTool(Tool):
    name = "media_control"
    description = "Control media playback and system volume (play/pause, next, previous, stop, volume up/down, mute)."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="action", type="string", description="What to do.", enum=sorted(sc.MEDIA_KEYS)),
        ToolParameter(
            name="times",
            type="integer",
            description="Repeat count, for volume steps (each step is about 2%).",
            required=False,
        ),
    ]

    async def execute(self, action: str, times: int = 1, **kwargs: Any) -> ToolResult:
        if action not in sc.MEDIA_KEYS:
            return ToolResult(success=False, error=f"Unknown action '{action}'.")
        try:
            await asyncio.to_thread(sc.press_media_key, action, times)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, result=f"Done: {action}" + (f" x{times}" if times > 1 else ""))


class LockScreenTool(Tool):
    name = "lock_screen"
    description = "Lock the computer (like pressing Win+L)."
    permission_level = PermissionLevel.LOW_RISK
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            sc.lock_workstation()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, result="Screen locked.")


class SendNotificationTool(Tool):
    name = "send_notification"
    description = "Show a desktop notification (toast) to the user."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="title", type="string", description="Notification title."),
        ToolParameter(name="message", type="string", description="Notification text."),
    ]

    async def execute(self, title: str, message: str, **kwargs: Any) -> ToolResult:
        if not sc.show_desktop_notification(title, message):
            return ToolResult(success=False, error="Desktop notifications aren't available on this system.")
        return ToolResult(success=True, result="Notification shown.")
