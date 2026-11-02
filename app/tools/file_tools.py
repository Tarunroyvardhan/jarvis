from __future__ import annotations

import asyncio
from typing import Any

from app.integrations.file_intelligence import FileIntelligenceService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult

# File service calls walk directories and read files synchronously, so
# every tool runs them in a worker thread to keep the event loop free.


class FindFilesTool(Tool):
    name = "find_files"
    description = "Find files whose name contains some text, within allowed directories."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="query", type="string", description="Filename text to search for."),
        ToolParameter(
            name="directory", type="string", description="Restrict search to this directory.", required=False
        ),
        ToolParameter(name="limit", type="integer", description="Maximum results (default 20).", required=False),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(
        self, query: str, directory: str | None = None, limit: int = 20, **kwargs: Any
    ) -> ToolResult:
        result = await asyncio.to_thread(
            self._service.find_files, query=query, directory=directory, limit=min(limit, 200)
        )
        if not result.success:
            return ToolResult(success=False, error=result.error)
        files = [{"path": f.path, "name": f.name, "size_bytes": f.size_bytes} for f in result.files]
        return ToolResult(success=True, result=files or "No matching files.", metadata={"count": len(files)})


class ListRecentFilesTool(Tool):
    name = "list_recent_files"
    description = "List the most recently modified files in allowed directories."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="directory", type="string", description="Restrict to this directory.", required=False
        ),
        ToolParameter(name="limit", type="integer", description="Maximum results.", required=False),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(
        self, directory: str | None = None, limit: int = 10, **kwargs: Any
    ) -> ToolResult:
        result = await asyncio.to_thread(
            self._service.list_recent_files, directory=directory, limit=min(limit, 200)
        )
        if not result.success:
            return ToolResult(success=False, error=result.error)
        files = [
            {"path": f.path, "name": f.name, "modified_at": f.modified_at} for f in result.files
        ]
        return ToolResult(success=True, result=files, metadata={"count": len(files)})


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "List the files and subfolders directly inside a folder (within allowed directories)."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="directory", type="string", description="Folder to list."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, directory: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.list_directory, directory)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a file's contents (text, PDF, or DOCX) from an allowed directory."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to read."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.read_file, path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class SearchFileContentsTool(Tool):
    name = "search_file_contents"
    description = "Search the contents of text files in allowed directories for a keyword."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="query", type="string", description="Text to search for."),
        ToolParameter(
            name="directory", type="string", description="Restrict search to this directory.", required=False
        ),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, query: str, directory: str | None = None, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(
            self._service.search_file_contents, query=query, directory=directory
        )
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(
            success=True, result=result.matches or "No matches.", metadata={"count": len(result.matches)}
        )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or overwrite a text file (or append to it) within allowed directories. "
        "Creating a new file needs no confirmation; overwriting an existing one does."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="path", type="string", description="Path of the file to write."),
        ToolParameter(name="content", type="string", description="Full text content to write."),
        ToolParameter(
            name="append",
            type="boolean",
            description="Append to the end of the file instead of replacing it.",
            required=False,
        ),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    def permission_for(self, path: str = "", append: bool = False, **kwargs: Any) -> PermissionLevel:
        if path and not append and self._service.file_exists(path):
            return PermissionLevel.CONFIRM_REQUIRED
        return PermissionLevel.LOW_RISK

    async def describe(self, path: str = "", content: str = "", **kwargs: Any) -> str:
        preview = content if len(content) <= 300 else content[:297] + "..."
        return f"Overwrite existing file {path} ({len(content)} chars) with:\n{preview}"

    async def execute(self, path: str, content: str, append: bool = False, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.write_file, path, content, append)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Create a folder (and any missing parents) within allowed directories."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="path", type="string", description="Folder path to create."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.create_folder, path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class CopyFileTool(Tool):
    name = "copy_file"
    description = "Copy a file or folder to a new location within allowed directories. Never overwrites."
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="source", type="string", description="File or folder to copy."),
        ToolParameter(name="destination", type="string", description="Destination path or folder."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, source: str, destination: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.copy_path, source, destination)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class MoveFileTool(Tool):
    name = "move_file"
    description = (
        "Move or rename a file or folder within allowed directories. Never overwrites. "
        "Requires user confirmation."
    )
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = [
        ToolParameter(name="source", type="string", description="File or folder to move."),
        ToolParameter(name="destination", type="string", description="New path or destination folder."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def describe(self, source: str = "", destination: str = "", **kwargs: Any) -> str:
        return f"Move {source} -> {destination}"

    async def execute(self, source: str, destination: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.move_path, source, destination)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Delete a file. Always requires explicit user confirmation."
    permission_level = PermissionLevel.ALWAYS_CONFIRM
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to delete."),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def describe(self, path: str = "", **kwargs: Any) -> str:
        return f"Permanently delete file: {path}"

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        result = await asyncio.to_thread(self._service.delete_file, path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)
