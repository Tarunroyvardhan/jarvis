import pytest

from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolResult
from app.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Echoes back its input."
    permission_level = PermissionLevel.READ_ONLY
    parameters = []

    async def execute(self, **kwargs):
        return ToolResult(success=True, result=kwargs.get("text", ""))


class BrokenTool(Tool):
    name = "broken"
    description = "Always raises."
    permission_level = PermissionLevel.READ_ONLY
    parameters = []

    async def execute(self, **kwargs):
        raise RuntimeError("simulated failure")


class GatedTool(Tool):
    name = "gated"
    description = "Requires confirmation (level 2)."
    permission_level = PermissionLevel.CONFIRM_REQUIRED
    parameters = []

    async def describe(self, **kwargs):
        return f"Do the gated thing with {kwargs}"

    async def execute(self, **kwargs):
        return ToolResult(success=True, result="executed")


class AlwaysConfirmTool(Tool):
    name = "critical"
    description = "Level 3, always confirm."
    permission_level = PermissionLevel.ALWAYS_CONFIRM
    parameters = []

    async def execute(self, **kwargs):
        return ToolResult(success=True, result="executed")


@pytest.mark.asyncio
async def test_unknown_tool_cannot_execute():
    registry = ToolRegistry()
    result = await registry.execute("does_not_exist")
    assert result.success is False
    assert "Unknown tool" in result.error


@pytest.mark.asyncio
async def test_tool_failure_is_reported():
    registry = ToolRegistry()
    registry.register(BrokenTool())

    result = await registry.execute("broken")

    assert result.success is False
    assert "broken" in result.error
    assert "simulated failure" in result.error


@pytest.mark.asyncio
async def test_successful_tool_call_returns_result():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = await registry.execute("echo", text="hello")

    assert result.success is True
    assert result.result == "hello"


@pytest.mark.asyncio
async def test_gated_tool_denied_when_no_confirm_callback_available():
    registry = ToolRegistry()
    registry.register(GatedTool())

    result = await registry.execute("gated")

    assert result.success is False
    assert "requires user confirmation" in result.error


@pytest.mark.asyncio
async def test_gated_tool_executes_when_confirmed():
    registry = ToolRegistry()
    registry.register(GatedTool())

    async def always_approve(description: str) -> bool:
        return True

    result = await registry.execute("gated", always_approve, text="hi")

    assert result.success is True
    assert result.result == "executed"


@pytest.mark.asyncio
async def test_gated_tool_cancelled_when_declined():
    registry = ToolRegistry()
    registry.register(GatedTool())

    async def always_decline(description: str) -> bool:
        return False

    result = await registry.execute("gated", always_decline)

    assert result.success is False
    assert "cancelled" in result.error.lower()


@pytest.mark.asyncio
async def test_confirm_callback_receives_tool_description():
    registry = ToolRegistry()
    registry.register(GatedTool())

    received = []

    async def capture(description: str) -> bool:
        received.append(description)
        return True

    await registry.execute("gated", capture, text="delete something")

    assert len(received) == 1
    assert "delete something" in received[0]


@pytest.mark.asyncio
async def test_always_confirm_level_also_requires_confirmation():
    registry = ToolRegistry()
    registry.register(AlwaysConfirmTool())

    result_no_callback = await registry.execute("critical")
    assert result_no_callback.success is False

    async def approve(description: str) -> bool:
        return True

    result_approved = await registry.execute("critical", approve)
    assert result_approved.success is True


@pytest.mark.asyncio
async def test_broken_confirm_callback_is_reported_not_raised():
    registry = ToolRegistry()
    registry.register(GatedTool())

    async def broken_confirm(description: str) -> bool:
        raise RuntimeError("UI crashed")

    result = await registry.execute("gated", broken_confirm)

    assert result.success is False
    assert "Confirmation failed" in result.error


@pytest.mark.asyncio
async def test_declined_confirmation_does_not_execute_tool():
    """Critical safety property: declining must actually prevent execution,
    not just report a decline while running anyway."""
    executed = []

    class TrackingTool(Tool):
        name = "tracked"
        description = "Tracks whether it ran."
        permission_level = PermissionLevel.CONFIRM_REQUIRED
        parameters = []

        async def execute(self, **kwargs):
            executed.append(True)
            return ToolResult(success=True, result="ran")

    registry = ToolRegistry()
    registry.register(TrackingTool())

    async def decline(description: str) -> bool:
        return False

    await registry.execute("tracked", decline)

    assert executed == []


def test_duplicate_registration_raises():
    registry = ToolRegistry()
    registry.register(EchoTool())
    with pytest.raises(ValueError):
        registry.register(EchoTool())


def test_claude_schemas_includes_registered_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())

    schemas = registry.claude_schemas()

    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"
    assert "input_schema" in schemas[0]
