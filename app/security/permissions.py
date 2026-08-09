"""
Permission model for tool execution.

  LEVEL 0 — read only: always allowed, no confirmation
  LEVEL 1 — low-risk modification: always allowed, no confirmation
  LEVEL 2 — requires explicit user confirmation before executing
  LEVEL 3 — always requires explicit confirmation (reserved for the
            highest-stakes actions: deletions, purchases, sending
            messages to other people, publishing, installing software)

Levels 2 and 3 share the same mechanical treatment in this checker today
(both require confirmation) — the distinction matters for which actions
get assigned which level as new tools are added, not for how the checker
behaves. If that ever needs to diverge (e.g. level 3 requiring a second,
stronger confirmation), it changes here without touching callers.
"""

from __future__ import annotations

from enum import IntEnum


class PermissionLevel(IntEnum):
    READ_ONLY = 0
    LOW_RISK = 1
    CONFIRM_REQUIRED = 2
    ALWAYS_CONFIRM = 3


class PermissionDenied(Exception):
    """Raised when a permission level cannot be cleared — no confirmation
    handler was available for a level that requires one, or confirmation
    was explicitly declined. Callers convert this into a structured
    ToolResult rather than letting it propagate as a crash."""


class PermissionChecker:
    """Decides whether a tool call may proceed automatically or needs
    explicit user confirmation first. Does not execute anything and does
    not itself ask the user anything — that's the confirmation callback's
    job, supplied by the caller (see ToolRegistry.execute)."""

    AUTO_APPROVED_LEVELS = {PermissionLevel.READ_ONLY, PermissionLevel.LOW_RISK}
    CONFIRMATION_LEVELS = {PermissionLevel.CONFIRM_REQUIRED, PermissionLevel.ALWAYS_CONFIRM}

    def requires_confirmation(self, level: PermissionLevel) -> bool:
        if level in self.AUTO_APPROVED_LEVELS:
            return False
        if level in self.CONFIRMATION_LEVELS:
            return True
        raise ValueError(f"Unknown permission level: {level}")
