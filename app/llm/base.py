"""
Provider-agnostic LLM interface.

Nothing outside this module (and its concrete implementations) should
know which LLM vendor is in use. The rest of the application talks to
`LLMProvider` only, so swapping Claude for another provider later is a
matter of adding a new class here, not rewriting the assistant.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    # Raw provider-native content blocks. When present they are replayed
    # to the API verbatim instead of `content` — required for tool-use
    # round trips, thinking blocks, server-tool results and compaction
    # blocks, all of which must come back to the API exactly as produced.
    raw_blocks: list[dict] | None = None


@dataclass(frozen=True)
class ToolCallRequest:
    """A single tool invocation the model is asking the app to perform."""

    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class LLMResponse:
    """Structured result from a completion call.

    `success=False` means the call failed outright (network error, auth
    error, refusal, etc.) — the assistant must surface this honestly
    rather than inventing a reply.

    `tool_calls` is populated when the model wants the app to run one or
    more client-side tools. `stop_reason` lets the caller distinguish a
    normal finish from a tool-use turn or a paused server-side tool loop
    ("pause_turn"), which must be resumed by re-sending the conversation.

    `activity` carries short human-readable notes about work the provider
    did server-side this call (e.g. 'web_search: "weather toronto"'), so
    the UI can show progress.
    """

    success: bool
    content: str = ""
    error: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    stop_reason: str | None = None
    raw_blocks: list[dict] | None = None
    activity: list[str] = field(default_factory=list)


class LLMProvider(ABC):
    """Abstract base class every LLM backend must implement."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send a conversation to the model and return a structured response.

        `tools` is an optional list of provider-agnostic tool schemas (as
        produced by Tool.to_claude_schema()). Passing None or an empty
        list means no client-side tools are offered this turn.
        """
        raise NotImplementedError
