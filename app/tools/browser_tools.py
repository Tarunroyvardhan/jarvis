"""
Browser tools: let Jarvis operate websites in a real browser window —
log in, search, fill forms, read pages that need JavaScript.

For simply looking something up, web_search / web_fetch (server-side) are
faster; these tools are for interacting with sites.

Clicking and typing are Level 1 so multi-step browsing stays usable; the
system prompt tells the model to stop and ask before any final click that
buys, posts, sends or submits something.
"""

from __future__ import annotations

from typing import Any

from app.integrations.browser import BrowserError, BrowserSession
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class _BrowserTool(Tool):
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    async def _wrap(self, coro) -> ToolResult:
        try:
            return ToolResult(success=True, result=await coro)
        except BrowserError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Browser error: {exc}")


class BrowserNavigateTool(_BrowserTool):
    name = "browser_navigate"
    description = (
        "Open a URL in Jarvis's automated browser window and return the page text "
        "plus numbered interactive elements."
    )
    parameters = [ToolParameter(name="url", type="string", description="URL to open.")]

    async def execute(self, url: str, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.navigate(url))


class BrowserSnapshotTool(_BrowserTool):
    name = "browser_snapshot"
    description = "Re-read the current browser page: text and numbered interactive elements."
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.snapshot())


class BrowserClickTool(_BrowserTool):
    name = "browser_click"
    description = "Click an element in the browser, by its number from the latest snapshot (preferred) or by visible text."
    parameters = [
        ToolParameter(name="element_id", type="integer", description="Element number from the snapshot.", required=False),
        ToolParameter(name="text", type="string", description="Visible text to click, if no number.", required=False),
    ]

    async def execute(self, element_id: int | None = None, text: str | None = None, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.click(element_id=element_id, text=text))


class BrowserTypeTool(_BrowserTool):
    name = "browser_type"
    description = "Type text into an input field in the browser (replacing its contents), optionally pressing Enter."
    parameters = [
        ToolParameter(name="element_id", type="integer", description="Input element number from the snapshot."),
        ToolParameter(name="text", type="string", description="Text to enter."),
        ToolParameter(name="submit", type="boolean", description="Press Enter afterwards.", required=False),
    ]

    async def execute(self, element_id: int, text: str, submit: bool = False, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.type_text(element_id, text, submit))


class BrowserPressKeyTool(_BrowserTool):
    name = "browser_press_key"
    description = "Press a keyboard key in the browser, e.g. Enter, Escape, Tab, ArrowDown, PageDown."
    parameters = [ToolParameter(name="key", type="string", description="Key name.")]

    async def execute(self, key: str, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.press_key(key))


class BrowserScrollTool(_BrowserTool):
    name = "browser_scroll"
    description = "Scroll the browser page up or down to reveal more elements."
    parameters = [
        ToolParameter(name="direction", type="string", description="Direction.", enum=["down", "up"], required=False)
    ]

    async def execute(self, direction: str = "down", **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.scroll(direction))


class BrowserBackTool(_BrowserTool):
    name = "browser_back"
    description = "Go back to the previous page in the browser."
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await self._wrap(self._session.back())


class BrowserScreenshotTool(_BrowserTool):
    name = "browser_screenshot"
    description = "Take a screenshot of the browser page to see its layout or images."
    permission_level = PermissionLevel.READ_ONLY
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            block = await self._session.screenshot()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Browser screenshot failed: {exc}")
        return ToolResult(success=True, result="Browser screenshot:", content_blocks=[block])


class BrowserCloseTool(_BrowserTool):
    name = "browser_close"
    description = "Close Jarvis's browser window."
    parameters: list = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        await self._session.close()
        return ToolResult(success=True, result="Browser closed.")


def browser_tools(session: BrowserSession) -> list[Tool]:
    return [
        BrowserNavigateTool(session),
        BrowserSnapshotTool(session),
        BrowserClickTool(session),
        BrowserTypeTool(session),
        BrowserPressKeyTool(session),
        BrowserScrollTool(session),
        BrowserBackTool(session),
        BrowserScreenshotTool(session),
        BrowserCloseTool(session),
    ]
