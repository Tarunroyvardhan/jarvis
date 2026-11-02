"""ClaudeProvider request shape and response parsing, against real SDK
response objects but a fake transport (no network)."""

import pytest
from anthropic.types.beta import BetaMessage

from app.llm.base import Message, Role
from app.llm.claude import ClaudeProvider


def _message(content, stop_reason="end_turn"):
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": content,
        }
    )


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _provider(response, **kwargs):
    provider = ClaudeProvider(api_key="sk-test", model="claude-opus-5-5", **kwargs)
    fake = _FakeMessages(response)
    provider._client.beta.messages = fake  # type: ignore[attr-defined]
    return provider, fake


@pytest.mark.asyncio
async def test_request_uses_adaptive_thinking_effort_compaction_and_caching():
    provider, fake = _provider(_message([{"type": "text", "text": "hi"}]), effort="high")

    await provider.complete(
        [Message(role=Role.USER, content="hello")],
        system_prompt="sys",
        tools=[{"name": "echo", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
    )

    kw = fake.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}
    assert kw["context_management"] == {"edits": [{"type": "compact_20260112"}]}
    assert "compact-2026-01-12" in kw["betas"]
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["system"] == "sys"
    tool_names = [t["name"] for t in kw["tools"]]
    assert tool_names[0] == "echo"
    assert "web_search" in tool_names and "web_fetch" in tool_names
    assert kw["fallbacks"] == "default"


@pytest.mark.asyncio
async def test_web_tools_can_be_disabled():
    provider, fake = _provider(_message([{"type": "text", "text": "hi"}]), web_search=False)
    await provider.complete([Message(role=Role.USER, content="hello")])
    assert "tools" not in fake.kwargs


@pytest.mark.asyncio
async def test_all_blocks_are_preserved_for_replay():
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "toronto weather"}},
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "t1", "name": "echo", "input": {"a": 1}},
    ]
    provider, _ = _provider(_message(content, stop_reason="tool_use"))

    response = await provider.complete([Message(role=Role.USER, content="hi")])

    assert response.success
    assert [b["type"] for b in response.raw_blocks] == ["thinking", "server_tool_use", "text", "tool_use"]
    assert response.raw_blocks[0]["signature"] == "sig"
    assert response.tool_calls[0].name == "echo"
    assert response.content == "Let me check."
    assert response.activity == ['web_search: "toronto weather"']


@pytest.mark.asyncio
async def test_raw_blocks_are_sent_verbatim():
    provider, fake = _provider(_message([{"type": "text", "text": "ok"}]))
    blocks = [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]

    await provider.complete([Message(role=Role.USER, content="", raw_blocks=blocks)])

    assert fake.kwargs["messages"] == [{"role": "user", "content": blocks}]


@pytest.mark.asyncio
async def test_refusal_is_reported_as_failure():
    provider, _ = _provider(_message([], stop_reason="refusal"))
    response = await provider.complete([Message(role=Role.USER, content="hi")])
    assert response.success is False
    assert "declined" in response.error


def test_missing_api_key_rejected():
    with pytest.raises(ValueError):
        ClaudeProvider(api_key="", model="claude-opus-5-5")
