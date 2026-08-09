from __future__ import annotations

from datetime import datetime
from typing import Any

from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolResult


class GetCurrentTimeTool(Tool):
    name = "get_current_time"
    description = "Get the current date and time."
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        now = datetime.now()
        return ToolResult(
            success=True,
            result=now.strftime("%A, %B %d, %Y %I:%M %p"),
            metadata={"iso": now.isoformat()},
        )
