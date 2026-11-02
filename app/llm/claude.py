"""Claude (Anthropic API) implementation of LLMProvider.

Request shape, and why:
  * Adaptive thinking is always on for current models; `effort` is the
    knob for how hard the model thinks (and therefore latency/cost).
  * Every content block the API returns — thinking, text, tool_use,
    server_tool_use, web search results, compaction — is replayed back
    verbatim. Dropping or rewriting any of them breaks thinking
    continuity and server-side compaction.
  * Server-side compaction summarises old context once the conversation
    gets long, so history never has to be trimmed client-side (trimming
    used to split tool_use/tool_result pairs and 400 the request).
  * Web search / web fetch run on Anthropic's side; no client code needed.
  * The system prompt and tool list are static for a session, and the
    whole prefix is marked cacheable, so repeat turns are cheap.
"""

from __future__ import annotations

import logging

import anthropic

from app.llm.base import LLMProvider, LLMResponse, Message, Role, ToolCallRequest

logger = logging.getLogger(__name__)

COMPACTION_BETA = "compact-2026-01-12"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
# On a safety-classifier decline the API re-runs the request on a suitable
# model inside the same call instead of just stopping.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]


def _describe_server_tool(block: dict) -> str:
    name = block.get("name", "server_tool")
    if name == "code_execution":
        # web_search/web_fetch filter their results with code under the hood.
        return "filtering results"
    tool_input = block.get("input") or {}
    detail = tool_input.get("query") or tool_input.get("url") or ""
    return f'{name}: "{detail}"' if detail else name


class ClaudeProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 16000,
        effort: str = "medium",
        web_search: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required to construct ClaudeProvider")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._web_search = web_search

    @property
    def model(self) -> str:
        return self._model

    def _to_api_message(self, m: Message) -> dict:
        content = m.raw_blocks if m.raw_blocks is not None else m.content
        return {"role": m.role.value, "content": content}

    def _build_request(
        self, messages: list[Message], system_prompt: str | None, tools: list[dict] | None
    ) -> dict:
        all_tools = list(tools or [])
        if self._web_search:
            all_tools += WEB_TOOLS

        betas = [COMPACTION_BETA]
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [self._to_api_message(m) for m in messages if m.role != Role.SYSTEM],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._effort},
            "context_management": {"edits": [{"type": "compact_20260112"}]},
            # Caches the longest stable prefix (tools + system + history).
            "cache_control": {"type": "ephemeral"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if all_tools:
            kwargs["tools"] = all_tools
        if self._model in FALLBACK_MODELS:
            betas.append(FALLBACK_BETA)
            kwargs["fallbacks"] = "default"
        kwargs["betas"] = betas
        return kwargs

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        kwargs = self._build_request(messages, system_prompt, tools)

        try:
            response = await self._client.beta.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            return LLMResponse(success=False, error="The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.")
        except anthropic.NotFoundError as exc:
            return LLMResponse(success=False, error=f"Model '{self._model}' not found ({exc.message}). Check CLAUDE_MODEL.")
        except anthropic.RateLimitError:
            return LLMResponse(success=False, error="Rate limited by the Claude API. Try again in a moment.")
        except anthropic.BadRequestError as exc:
            logger.error("Claude rejected the request: %s", exc)
            return LLMResponse(success=False, error=f"Claude rejected the request: {exc.message}")
        except anthropic.APIStatusError as exc:
            logger.error("Claude API error: %s", exc)
            return LLMResponse(success=False, error=f"Claude API error ({exc.status_code}): {exc.message}")
        except anthropic.APIConnectionError as exc:
            logger.error("Claude connection error: %s", exc)
            return LLMResponse(success=False, error=f"Could not reach the Claude API: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure honestly
            logger.exception("Unexpected error calling Claude")
            return LLMResponse(success=False, error=f"Unexpected error: {exc}")

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        raw_blocks: list[dict] = []
        activity: list[str] = []

        for block in response.content:
            # Keeps exactly the fields the API sent (minus nulls), so the
            # block round-trips unchanged on the next request.
            raw = block.to_dict(mode="json", exclude_none=True)
            raw_blocks.append(raw)
            block_type = raw.get("type")
            if block_type == "text":
                text_parts.append(raw.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(id=raw["id"], name=raw["name"], input=raw.get("input") or {})
                )
            elif block_type == "server_tool_use":
                activity.append(_describe_server_tool(raw))

        if response.stop_reason == "refusal":
            return LLMResponse(
                success=False,
                error="Claude declined this request for safety reasons.",
                stop_reason="refusal",
                model=response.model,
            )

        usage = response.usage
        return LLMResponse(
            success=True,
            content="\n".join(t for t in text_parts if t).strip(),
            model=response.model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw_blocks=raw_blocks,
            activity=activity,
        )
