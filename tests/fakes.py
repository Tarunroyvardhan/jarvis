from __future__ import annotations

from app.llm.base import LLMProvider, LLMResponse, Message


class FakeLLMProvider(LLMProvider):
    """Deterministic stand-in for a real LLM, for fast offline tests.

    Can either always return the same fixed reply, or be given a queue of
    canned LLMResponse objects (via `responses`) to return one-per-call —
    the latter is what lets tests drive multi-step tool-call loops.
    """

    def __init__(
        self,
        reply: str = "Hello.",
        fail: bool = False,
        error: str = "boom",
        responses: list[LLMResponse] | None = None,
    ) -> None:
        self.reply = reply
        self.fail = fail
        self.error = error
        self._responses = list(responses) if responses is not None else None
        self.calls: list[tuple[list[Message], str | None, list[dict] | None]] = []

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        self.calls.append((list(messages), system_prompt, tools))

        if self._responses is not None:
            if not self._responses:
                raise AssertionError("FakeLLMProvider ran out of canned responses")
            return self._responses.pop(0)

        if self.fail:
            return LLMResponse(success=False, error=self.error)
        return LLMResponse(success=True, content=self.reply, model="fake-model")
