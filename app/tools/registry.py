"""
ToolRegistry — the single place that knows every tool that exists.

Responsibilities:
  * hold registered tools by name
  * produce the Claude-facing schema list
  * execute a named tool safely: unknown tools, permission failures,
    declined confirmations, and tool-internal exceptions are ALL
    converted into a structured ToolResult rather than raised — the
    assistant loop should never have to guard against a random exception
    coming out of tool execution.

Level 2/3 tools require a confirmation callback to be passed in. This
keeps the registry itself free of any actual user-interaction code (no
input(), no prints) — the caller decides how confirmation is surfaced
(terminal prompt, voice, future UI), the registry just enforces that it
happened before executing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.security.permissions import PermissionChecker, PermissionLevel
from app.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

ConfirmationCallback = Callable[[str], Awaitable[bool]]


class ToolRegistry:
    def __init__(self, permission_checker: PermissionChecker | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._permissions = permission_checker or PermissionChecker()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def claude_schemas(self) -> list[dict]:
        return [tool.to_claude_schema() for tool in self._tools.values()]

    async def execute(
        self,
        tool_name: str,
        confirm: ConfirmationCallback | None = None,
        /,
        **kwargs,
    ) -> ToolResult:
        """`tool_name` and `confirm` are positional-only (the `/`) so they
        can never collide with a tool's own parameter names arriving via
        **kwargs — e.g. open_application's parameter is itself called
        "name", which would otherwise clash with this method's own
        argument of the same name. This is a real bug this project hit
        once already; positional-only params make the whole class of
        collision impossible rather than just avoiding today's known
        cases.
        """
        tool = self.get(tool_name)
        if tool is None:
            logger.warning("Requested unknown tool: %s", tool_name)
            return ToolResult(success=False, error=f"Unknown tool: '{tool_name}'")

        try:
            level = max(tool.permission_level, tool.permission_for(**kwargs))
        except Exception:  # noqa: BLE001 - when in doubt, require confirmation
            logger.exception("permission_for failed for tool '%s'", tool_name)
            level = PermissionLevel.ALWAYS_CONFIRM

        if self._permissions.requires_confirmation(level):
            if confirm is None:
                logger.warning(
                    "Tool '%s' requires confirmation but no confirmation handler "
                    "is available in this context; denying.",
                    tool_name,
                )
                return ToolResult(
                    success=False,
                    error=(
                        f"'{tool_name}' requires user confirmation, but no confirmation "
                        "handler is available right now."
                    ),
                )

            try:
                description = await tool.describe(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.exception("describe() failed for tool '%s'", tool_name)
                description = f"Run '{tool_name}' with {kwargs} (description unavailable: {exc})"
            try:
                approved = await confirm(description)
            except Exception as exc:  # noqa: BLE001 - a broken confirm callback must not crash the loop
                logger.exception("Confirmation callback failed for tool '%s'", tool_name)
                return ToolResult(success=False, error=f"Confirmation failed: {exc}")

            if not approved:
                logger.info("Tool '%s' declined by user: %s", tool_name, description)
                return ToolResult(success=False, error="Action cancelled — not confirmed by user.")

        try:
            result = await tool.execute(**kwargs)
        except TypeError as exc:
            # Almost always the model passing a missing/unexpected argument.
            logger.warning("Bad arguments for tool '%s': %s", tool_name, exc)
            return ToolResult(success=False, error=f"Invalid arguments for '{tool_name}': {exc}")
        except Exception as exc:  # noqa: BLE001 - tool internals must never crash the loop
            logger.exception("Tool '%s' raised an unhandled exception", tool_name)
            return ToolResult(success=False, error=f"Tool '{tool_name}' failed: {exc}")

        logger.info(
            "Tool executed: name=%s permission=%s success=%s",
            tool_name,
            level.name,
            result.success,
        )
        return result
