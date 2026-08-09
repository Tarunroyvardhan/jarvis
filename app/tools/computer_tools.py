from __future__ import annotations

from typing import Any

from app.integrations.computer_controller import ComputerController
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class OpenApplicationTool(Tool):
    name = "open_application"
    description = "Open an application by name, from a fixed list of known applications."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="name", type="string", description="Name of the application to open."),
    ]

    def __init__(self, controller: ComputerController) -> None:
        self._controller = controller

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        result = self._controller.open_application(name)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=f"Opened {name}.")


class OpenWebsiteTool(Tool):
    name = "open_website"
    description = "Open a URL in the default web browser."
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
