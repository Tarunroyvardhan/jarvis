"""
Base types for the tool system.

Every tool is a small, self-contained class with a declared JSON schema
for its parameters, a permission level, and an execute() method that
NEVER raises past its own boundary — it always returns a ToolResult so
the assistant can honestly report success or failure to the user.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.security.permissions import PermissionLevel


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str  # JSON schema type: "string", "integer", "boolean", etc.
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass(frozen=True)
class ToolResult:
    success: bool
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Abstract base every tool must implement."""

    name: str
    description: str
    permission_level: PermissionLevel
    parameters: list[ToolParameter] = []

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool. Must catch its own exceptions and return ToolResult."""
        raise NotImplementedError

    async def describe(self, **kwargs: Any) -> str:
        """Human-readable summary of what this specific call would do,
        shown to the user for confirmation on Level 2/3 tools. Default is
        generic; tools that actually need confirmation should override
        this with something concrete (e.g. "Delete note #3: 'buy milk'")
        rather than leaving the user confirming a vague description of
        their own request.

        Async so a tool can do a real lookup to build an accurate
        description (e.g. fetching an event's title before asking to
        delete it) rather than confirming blind based on an id alone.
        """
        return f"Run '{self.name}' with {kwargs}" if kwargs else f"Run '{self.name}'"

    def to_claude_schema(self) -> dict:
        """Convert this tool's declaration into Claude's tool-use JSON schema."""
        properties = {}
        required = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
