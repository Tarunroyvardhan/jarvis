"""Data model for stored memories."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MemoryType(str, Enum):
    CONVERSATION = "conversation"
    PROFILE = "profile"
    EPISODIC = "episodic"
    # TASK and KNOWLEDGE are reserved for later phases (tasks already have
    # their own table; knowledge/document indexing needs file intelligence
    # first) but the type is declared now so the schema doesn't need to
    # change shape when those land.
    TASK = "task"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True)
class Memory:
    id: int
    content: str
    type: MemoryType
    created_at: datetime
    updated_at: datetime
    importance: int = 1
    source: str | None = None
    metadata: dict = field(default_factory=dict)
    expires_at: datetime | None = None

    @property
    def is_permanent(self) -> bool:
        return self.expires_at is None
