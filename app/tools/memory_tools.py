"""
Memory tools exposed to Claude.

Important: nothing in this file decides *when* memory should be used —
that judgment call belongs entirely to Claude, made from understanding
the user's sentence. These classes only implement *what happens* once
Claude has already decided to call remember/recall/forget. There is no
keyword or regex trigger list anywhere in this app that maps phrases
like "remember that" to an action.
"""

from __future__ import annotations

from typing import Any

from app.memory.models import MemoryType
from app.memory.repository import MemoryRepository
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult

_TYPE_CHOICES = [t.value for t in MemoryType]


class RememberTool(Tool):
    name = "remember"
    description = (
        "Save something to memory. Use `permanent=true` only when the user "
        "explicitly asks you to remember/save something long-term — those "
        "memories last until the user asks you to forget them. Otherwise "
        "(e.g. noting something about the current conversation for your own "
        "context) leave permanent=false; that memory auto-expires in about "
        "a week."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="content", type="string", description="The information to remember."),
        ToolParameter(
            name="type",
            type="string",
            description="Category of memory.",
            enum=_TYPE_CHOICES,
        ),
        ToolParameter(
            name="permanent",
            type="boolean",
            description=(
                "True only if the user explicitly asked you to remember this "
                "long-term. False for ordinary auto-expiring context."
            ),
        ),
    ]

    def __init__(self, repository: MemoryRepository) -> None:
        self._repo = repository

    async def execute(
        self, content: str, type: str, permanent: bool, **kwargs: Any
    ) -> ToolResult:
        try:
            memory_type = MemoryType(type)
        except ValueError:
            return ToolResult(success=False, error=f"Invalid memory type: '{type}'")

        try:
            memory = self._repo.remember(
                content=content,
                type=memory_type,
                permanent=permanent,
                source="user_explicit" if permanent else "assistant_auto",
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        expiry_note = "permanently" if memory.is_permanent else "for about a week"
        return ToolResult(
            success=True,
            result=f"Remembered (id={memory.id}), stored {expiry_note}.",
            metadata={"id": memory.id, "permanent": memory.is_permanent},
        )


class RecallTool(Tool):
    name = "recall"
    description = (
        "Search memory for relevant saved information — profile facts, "
        "past episodes, or earlier conversation context."
    )
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Keyword(s) to search for in saved memories.",
            required=False,
        ),
        ToolParameter(
            name="type",
            type="string",
            description="Restrict to one memory category.",
            required=False,
            enum=_TYPE_CHOICES,
        ),
    ]

    def __init__(self, repository: MemoryRepository) -> None:
        self._repo = repository

    async def execute(
        self, query: str | None = None, type: str | None = None, **kwargs: Any
    ) -> ToolResult:
        memory_type = None
        if type:
            try:
                memory_type = MemoryType(type)
            except ValueError:
                return ToolResult(success=False, error=f"Invalid memory type: '{type}'")

        memories = self._repo.retrieve(type=memory_type, query=query, limit=10)
        results = [
            {"id": m.id, "content": m.content, "type": m.type.value, "permanent": m.is_permanent}
            for m in memories
        ]
        return ToolResult(success=True, result=results, metadata={"count": len(results)})


class ForgetTool(Tool):
    name = "forget"
    description = (
        "Delete a previously saved memory. Provide the memory's id if known "
        "(e.g. from a prior recall), otherwise a search query matching its "
        "content — if multiple memories match, none are deleted and the "
        "matches are returned so the user can clarify which one."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(
            name="memory_id", type="integer", description="Exact id of the memory to delete.", required=False
        ),
        ToolParameter(
            name="query",
            type="string",
            description="Text to search for if the id isn't known.",
            required=False,
        ),
    ]

    def __init__(self, repository: MemoryRepository) -> None:
        self._repo = repository

    async def execute(
        self, memory_id: int | None = None, query: str | None = None, **kwargs: Any
    ) -> ToolResult:
        if memory_id is not None:
            deleted = self._repo.forget(memory_id)
            if deleted:
                return ToolResult(success=True, result=f"Deleted memory {memory_id}.")
            return ToolResult(success=False, error=f"No memory found with id {memory_id}.")

        if not query:
            return ToolResult(success=False, error="Provide either memory_id or query.")

        matches = self._repo.retrieve(query=query, limit=5, include_expired=True)
        if not matches:
            return ToolResult(success=False, error=f"No memory found matching '{query}'.")
        if len(matches) > 1:
            candidates = [{"id": m.id, "content": m.content} for m in matches]
            return ToolResult(
                success=False,
                error="Multiple memories match; ask the user which id to delete.",
                metadata={"candidates": candidates},
            )

        deleted = self._repo.forget(matches[0].id)
        return ToolResult(success=deleted, result=f"Deleted memory {matches[0].id}.")
