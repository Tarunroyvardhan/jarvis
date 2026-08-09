"""Claude (Anthropic API) implementation of LLMProvider."""

from __future__ import annotations

import logging

import anthropic

from app.llm.base import LLMProvider, LLMResponse, Message, Role, ToolCallRequest

logger = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required to construct ClaudeProvider")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def _to_api_message(self, m: Message) -> dict:
        # Turns that carry raw tool_use / tool_result blocks are replayed
        # verbatim; plain turns use simple string content.
        content = m.raw_blocks if m.raw_blocks is not None else m.content
        return {"role": m.role.value, "content": content}

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        api_messages = [
            self._to_api_message(m) for m in messages if m.role != Role.SYSTEM
        ]

        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system_prompt or "",
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            logger.error("Claude API error: %s", exc)
            return LLMResponse(success=False, error=f"Claude API error: {exc}")
        except anthropic.APIConnectionError as exc:
            logger.error("Claude connection error: %s", exc)
            return LLMResponse(success=False, error=f"Could not reach Claude API: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure honestly
            logger.exception("Unexpected error calling Claude")
            return LLMResponse(success=False, error=f"Unexpected error: {exc}")

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        raw_blocks: list[dict] = []

        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(block.text)
                raw_blocks.append({"type": "text", "text": block.text})
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(id=block.id, name=block.name, input=block.input)
                )
                raw_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return LLMResponse(
            success=True,
            content="\n".join(text_parts).strip(),
            model=response.model,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            raw_blocks=raw_blocks,
        )
