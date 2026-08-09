from __future__ import annotations

from typing import Any

from app.integrations.news import NewsService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class GetNewsTool(Tool):
    name = "get_news"
    description = "Get recent news headlines, optionally filtered by topic/keyword."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="topic",
            type="string",
            description="Keyword to filter headlines by, e.g. 'AI' or 'climate'.",
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of headlines to return.",
            required=False,
        ),
    ]

    def __init__(self, news_service: NewsService) -> None:
        self._service = news_service

    async def execute(
        self, topic: str | None = None, limit: int = 5, **kwargs: Any
    ) -> ToolResult:
        result = await self._service.get_headlines(limit=limit, topic=topic)
        if not result.success:
            return ToolResult(success=False, error=result.error)

        headlines = [
            {"title": item.title, "source": item.source, "link": item.link}
            for item in result.items
        ]
        return ToolResult(success=True, result=headlines, metadata={"count": len(headlines)})
