import pytest

from app.core.assistant import Assistant, MAX_TOOL_ITERATIONS
from app.llm.base import LLMResponse, Role, ToolCallRequest
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolResult
from app.tools.registry import ToolRegistry
from tests.fakes import FakeLLMProvider


class EchoTool(Tool):
    name = "echo"
    description = "Echoes back its input."
    permission_level = PermissionLevel.READ_ONLY
    parameters = []

    async def execute(self, **kwargs):
        return ToolResult(success=True, result=kwargs.get("text", "echoed"))


class GatedTool(Tool):
    name = "gated_action"
    description = "A destructive action requiring confirmation."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = []

    async def describe(self, **kwargs):
        return "Do the gated destructive thing"

    async def execute(self, **kwargs):
        return ToolResult(success=True, result="destroyed")


@pytest.mark.asyncio
async def test_system_prompt_disambiguates_delete_note_from_forget():
    """Regression test: the system prompt previously described notes/tasks
    vaguely enough that Claude used the memory `forget` tool for "delete
    that note" instead of the actual `delete_note` tool, then claimed no
    delete capability existed at all. The prompt must name delete_note and
    delete_task explicitly and distinguish them from forget."""
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, name="Jarvis")

    prompt = assistant.system_prompt
    assert "delete_note" in prompt
    assert "delete_task" in prompt
    assert "forget" in prompt
    # the explicit disambiguation sentence, not just both words appearing
    assert "has no effect on notes or tasks" in prompt


@pytest.mark.asyncio
async def test_chat_returns_reply_from_provider():
    llm = FakeLLMProvider(reply="Hi there.")
    assistant = Assistant(llm=llm, name="Jarvis")

    response = await assistant.chat("Hello")

    assert response.success is True
    assert response.content == "Hi there."


@pytest.mark.asyncio
async def test_chat_maintains_short_term_history():
    llm = FakeLLMProvider(reply="Ack.")
    assistant = Assistant(llm=llm, name="Jarvis")

    await assistant.chat("first message")
    await assistant.chat("second message")

    sent_messages, _, _ = llm.calls[-1]
    contents = [m.content for m in sent_messages]
    assert "first message" in contents
    assert "Ack." in contents
    assert "second message" in contents


@pytest.mark.asyncio
async def test_history_trims_to_max_length():
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, name="Jarvis", max_history_messages=2)

    await assistant.chat("one")
    await assistant.chat("two")
    await assistant.chat("three")

    sent_messages, _, _ = llm.calls[-1]
    assert len(sent_messages) <= 2


@pytest.mark.asyncio
async def test_failed_call_does_not_leave_dangling_user_turn():
    llm = FakeLLMProvider(fail=True, error="network down")
    assistant = Assistant(llm=llm, name="Jarvis")

    response = await assistant.chat("hello")
    assert response.success is False
    assert response.error == "network down"
    assert assistant._history == []


@pytest.mark.asyncio
async def test_reset_clears_history():
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, name="Jarvis")

    await assistant.chat("hello")
    assert len(assistant._history) == 2  # user + assistant

    assistant.reset()
    assert assistant._history == []


@pytest.mark.asyncio
async def test_system_prompt_uses_configured_name():
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, name="Friday")

    assert "Friday" in assistant.system_prompt

    await assistant.chat("hello")
    _, system_prompt, _ = llm.calls[-1]
    assert "Friday" in system_prompt


@pytest.mark.asyncio
async def test_tool_call_loop_executes_tool_and_returns_final_reply():
    registry = ToolRegistry()
    registry.register(EchoTool())

    tool_call_response = LLMResponse(
        success=True,
        content="",
        tool_calls=[ToolCallRequest(id="call_1", name="echo", input={"text": "hi"})],
        stop_reason="tool_use",
        raw_blocks=[{"type": "tool_use", "id": "call_1", "name": "echo", "input": {"text": "hi"}}],
    )
    final_response = LLMResponse(success=True, content="The echo tool returned: hi")

    llm = FakeLLMProvider(responses=[tool_call_response, final_response])
    assistant = Assistant(llm=llm, tool_registry=registry, name="Jarvis")

    response = await assistant.chat("echo hi please")

    assert response.success is True
    assert response.content == "The echo tool returned: hi"
    assert len(llm.calls) == 2  # one to request the tool, one after the result


@pytest.mark.asyncio
async def test_tool_loop_gives_up_after_max_iterations():
    registry = ToolRegistry()
    registry.register(EchoTool())

    looping_response = LLMResponse(
        success=True,
        content="",
        tool_calls=[ToolCallRequest(id="call_x", name="echo", input={"text": "x"})],
        stop_reason="tool_use",
        raw_blocks=[{"type": "tool_use", "id": "call_x", "name": "echo", "input": {"text": "x"}}],
    )
    llm = FakeLLMProvider(responses=[looping_response] * MAX_TOOL_ITERATIONS)
    assistant = Assistant(llm=llm, tool_registry=registry, name="Jarvis")

    response = await assistant.chat("loop forever")

    assert response.success is False
    assert "tool round-trips" in response.error
    assert assistant._history == []  # rolled back, nothing dangling


@pytest.mark.asyncio
async def test_system_prompt_includes_current_time():
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, name="Jarvis")

    prompt = assistant.system_prompt
    assert "Current date and time:" in prompt


@pytest.mark.asyncio
async def test_chat_without_registry_still_works_for_plain_text():
    llm = FakeLLMProvider(reply="just chatting")
    assistant = Assistant(llm=llm, tool_registry=None, name="Jarvis")

    response = await assistant.chat("hello")

    assert response.success is True
    assert response.content == "just chatting"


@pytest.mark.asyncio
async def test_system_prompt_includes_relevant_memories(tmp_path):
    from app.memory.models import MemoryType
    from app.memory.repository import MemoryRepository

    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers morning meetings", MemoryType.PROFILE, permanent=True)

    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, memory_repository=repo, name="Jarvis")

    assert "prefers morning meetings" in assistant.system_prompt


@pytest.mark.asyncio
async def test_system_prompt_has_no_memory_section_when_nothing_stored(tmp_path):
    from app.memory.repository import MemoryRepository

    repo = MemoryRepository(db_path=tmp_path / "test.db")
    llm = FakeLLMProvider(reply="ok")
    assistant = Assistant(llm=llm, memory_repository=repo, name="Jarvis")

    assert "Things you know about the user" not in assistant.system_prompt


@pytest.mark.asyncio
async def test_successful_turn_is_persisted_as_conversation_memory(tmp_path):
    from app.memory.models import MemoryType
    from app.memory.repository import MemoryRepository

    repo = MemoryRepository(db_path=tmp_path / "test.db")
    llm = FakeLLMProvider(reply="Hi there.")
    assistant = Assistant(llm=llm, memory_repository=repo, name="Jarvis")

    await assistant.chat("hello")

    conversations = repo.retrieve(type=MemoryType.CONVERSATION, limit=10)
    assert len(conversations) == 1
    assert conversations[0].is_permanent is False
    assert "hello" in conversations[0].content


@pytest.mark.asyncio
async def test_failed_turn_is_not_persisted_as_conversation_memory(tmp_path):
    from app.memory.models import MemoryType
    from app.memory.repository import MemoryRepository

    repo = MemoryRepository(db_path=tmp_path / "test.db")
    llm = FakeLLMProvider(fail=True, error="down")
    assistant = Assistant(llm=llm, memory_repository=repo, name="Jarvis")

    await assistant.chat("hello")

    assert repo.retrieve(type=MemoryType.CONVERSATION, limit=10) == []


@pytest.mark.asyncio
async def test_confirmation_handler_is_passed_through_to_gated_tool():
    registry = ToolRegistry()
    registry.register(GatedTool())

    tool_call_response = LLMResponse(
        success=True,
        content="",
        tool_calls=[ToolCallRequest(id="call_1", name="gated_action", input={})],
        stop_reason="tool_use",
        raw_blocks=[{"type": "tool_use", "id": "call_1", "name": "gated_action", "input": {}}],
    )
    final_response = LLMResponse(success=True, content="Done.")
    llm = FakeLLMProvider(responses=[tool_call_response, final_response])

    approved_descriptions = []

    async def approve(description: str) -> bool:
        approved_descriptions.append(description)
        return True

    assistant = Assistant(
        llm=llm, tool_registry=registry, confirmation_handler=approve, name="Jarvis"
    )

    response = await assistant.chat("do the destructive thing")

    assert response.success is True
    assert len(approved_descriptions) == 1
    assert "gated destructive thing" in approved_descriptions[0]


@pytest.mark.asyncio
async def test_without_confirmation_handler_gated_tool_is_denied():
    """No confirmation_handler wired up at all (e.g. a future non-interactive
    context) must fail safe — deny, not silently execute."""
    registry = ToolRegistry()
    registry.register(GatedTool())

    tool_call_response = LLMResponse(
        success=True,
        content="",
        tool_calls=[ToolCallRequest(id="call_1", name="gated_action", input={})],
        stop_reason="tool_use",
        raw_blocks=[{"type": "tool_use", "id": "call_1", "name": "gated_action", "input": {}}],
    )
    final_response = LLMResponse(success=True, content="I couldn't do that without confirmation.")
    llm = FakeLLMProvider(responses=[tool_call_response, final_response])

    assistant = Assistant(llm=llm, tool_registry=registry, name="Jarvis")  # no confirmation_handler

    response = await assistant.chat("do the destructive thing")

    # The overall turn still completes (Claude gets told the tool was
    # denied and produces a final reply) — it's the tool itself that must
    # not have executed.
    assert response.success is True
