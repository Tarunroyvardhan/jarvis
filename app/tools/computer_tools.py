from __future__ import annotations

from typing import Any

from app.integrations.computer_controller import ComputerController
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult

_SCRIPT_EXTENSIONS = (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".com", ".lnk", ".py")


def _is_plain_app_name(name: str) -> bool:
    """'chrome', 'spotify', 'ms-settings:' -> True; anything that points at
    a specific file on disk ('C:\\x\\setup.exe', '..\\run.bat') -> False."""
    target = name.strip().lower()
    if not target or "\\" in target or "/" in target:
        return False
    if len(target) > 1 and target[1] == ":" and target[0].isalpha():
        return False  # drive path like c:setup.exe
    return not target.endswith(_SCRIPT_EXTENSIONS)


class OpenApplicationTool(Tool):
    name = "open_application"
    description = (
        "Open an installed application. Always pass its plain name as the user "
        "said it, e.g. 'chrome', 'word', 'spotify', 'vs code', or a settings "
        "page like 'ms-settings:' — never a file path; the app is located "
        "automatically and opens immediately. Only an unrecognised program or "
        "script path (e.g. a setup.exe in Downloads) asks the user to confirm."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="name", type="string", description="The application's name, e.g. 'chrome'."),
    ]

    def __init__(self, controller: ComputerController) -> None:
        self._controller = controller

    def permission_for(self, name: str = "", **kwargs: Any) -> PermissionLevel:
        # Opening an installed app is harmless and should just happen, by
        # name or by its real install path. Unknown paths and scripts still
        # need a "yes": that's how a malicious web page or email could try
        # to get a downloaded program executed.
        if (
            self._controller.is_allowed(name)
            or _is_plain_app_name(name)
            or self._controller.is_installed_app_path(name)
        ):
            return PermissionLevel.LOW_RISK
        return PermissionLevel.CONFIRM_REQUIRED

    async def describe(self, name: str = "", **kwargs: Any) -> str:
        return f"Launch the program or script at '{name}'"

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        if self._controller.is_allowed(name):
            result = self._controller.open_application(name)
        else:
            result = self._controller.launch_unlisted(name)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=f"Opened {name}.")


class OpenWebsiteTool(Tool):
    name = "open_website"
    description = "Open a URL in the user's default web browser (for them to look at)."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="url", type="string", description="Full URL, including http(s)://"),
    ]

    def __init__(self, controller: ComputerController) -> None:
        self._controller = controller

    async def execute(self, url: str, **kwargs: Any) -> ToolResult:
        result = self._controller.open_website(url)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=f"Opened {url} in the browser.")


class OpenFolderTool(Tool):
    name = "open_folder"
    description = "Open a folder in the file explorer. Must be within an allowed directory."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the folder to open."),
    ]

    def __init__(self, controller: ComputerController) -> None:
        self._controller = controller

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        result = self._controller.open_folder(path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=f"Opened folder {path}.")


class LaunchTerminalTool(Tool):
    name = "launch_terminal"
    description = "Open a new terminal window, optionally starting in a given (allowed) directory."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(
            name="directory",
            type="string",
            description="Directory to open the terminal in.",
            required=False,
        ),
    ]

    def __init__(self, controller: ComputerController) -> None:
        self._controller = controller

    async def execute(self, directory: str | None = None, **kwargs: Any) -> ToolResult:
        result = self._controller.launch_terminal(directory)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result="Terminal launched.")
