"""Structured-ish logging setup for JARVIS.

Kept simple in Phase 1: readable console logs with timestamps and levels.
Will grow into real structured logging (JSON, correlation IDs) around the
time we add the tool system and audit log in later phases.
"""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep third-party HTTP libraries quiet unless we're actually debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
