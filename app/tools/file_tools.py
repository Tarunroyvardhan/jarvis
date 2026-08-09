from __future__ import annotations

from typing import Any

from app.integrations.file_intelligence import FileIntelligenceService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class FindFilesTool(Tool):
    name = "find_files"
    description = "Find files by name within allowed directories."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="query", type="string", description="Filename text to search for."),
        ToolParameter(
            name="directory", type="string", description="Restrict search to this directory.", required=False
        ),
    ]

    def __init__(self, service: FileIntelligenceService) -> None:
        self._service = service

    async def execute(self, query: str, directory: str | None = None, **kwargs: Any) -> ToolResult:
        result = self._service.find_files(query=query, directory=directory)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        files = [{"path": f.path, "name": f.name, "size_bytes": f.size_bytes} for f in result.files]
        return ToolResult(success=True, result=files, metadata={"count": len(files)})


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
        result = self._service.list_recent_files(directory=directory, limit=limit)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        files = [
            {"path": f.path, "name": f.name, "modified_at": f.modified_at} for f in result.files
        ]
        return ToolResult(success=True, result=files, metadata={"count": len(files)})


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
        result = self._service.read_file(path)
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
        result = self._service.search_file_contents(query=query, directory=directory)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.matches, metadata={"count": len(result.matches)})


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
        result = self._service.delete_file(path)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(success=True, result=result.content)
