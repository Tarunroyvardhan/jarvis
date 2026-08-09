from unittest.mock import AsyncMock

import pytest

from app.integrations.email_service import EmailMessage, EmailResult, EmailSummary
from app.tools.email_tools import DraftEmailTool, ReadEmailTool, SearchEmailTool, SendEmailTool


@pytest.mark.asyncio
async def test_search_email_tool_formats_results():
    fake_service = AsyncMock()
    fake_service.search_messages.return_value = EmailResult(
        success=True,
        messages=[
            EmailSummary(id="m1", subject="Hello", sender="alice@example.com", snippet="hi", date="today")
        ],
    )

    tool = SearchEmailTool(email_service=fake_service)
    result = await tool.execute(query="from:alice")

    assert result.success is True
    assert result.result[0]["subject"] == "Hello"


@pytest.mark.asyncio
async def test_read_email_tool_returns_body():
    fake_service = AsyncMock()
    fake_service.read_message.return_value = EmailResult(
        success=True,
        message=EmailMessage(id="m1", subject="Hi", sender="a@b.com", date="today", body="Full body text"),
    )

    tool = ReadEmailTool(email_service=fake_service)
    result = await tool.execute(message_id="m1")

    assert result.success is True
    assert result.result["body"] == "Full body text"


@pytest.mark.asyncio
async def test_draft_email_tool_success():
    fake_service = AsyncMock()
    fake_service.create_draft.return_value = EmailResult(success=True, draft_id="d1")

    tool = DraftEmailTool(email_service=fake_service)
    result = await tool.execute(to="bob@example.com", subject="Hi", body="Hello")

    assert result.success is True
    assert "Not sent" in result.result
    assert result.metadata["draft_id"] == "d1"


@pytest.mark.asyncio
async def test_send_email_tool_is_always_confirm_level():
    from app.security.permissions import PermissionLevel

    fake_service = AsyncMock()
    tool = SendEmailTool(email_service=fake_service)

    assert tool.permission_level == PermissionLevel.ALWAYS_CONFIRM


@pytest.mark.asyncio
async def test_send_email_describe_shows_recipient_subject_and_preview():
    fake_service = AsyncMock()
    tool = SendEmailTool(email_service=fake_service)

    description = await tool.describe(
        to="bob@example.com", subject="Meeting notes", body="Here is a summary of our discussion today."
    )

    assert "bob@example.com" in description
    assert "Meeting notes" in description
    assert "summary of our discussion" in description


@pytest.mark.asyncio
async def test_send_email_describe_truncates_long_body():
    fake_service = AsyncMock()
    tool = SendEmailTool(email_service=fake_service)

    long_body = "x" * 500
    description = await tool.describe(to="bob@example.com", subject="Long", body=long_body)

    assert len(description) < 500 + 100  # truncated, not the full 500 chars
    assert "..." in description


@pytest.mark.asyncio
async def test_send_email_tool_success():
    fake_service = AsyncMock()
    fake_service.send_message.return_value = EmailResult(success=True, sent_id="s1")

    tool = SendEmailTool(email_service=fake_service)
    result = await tool.execute(to="bob@example.com", subject="Hi", body="Hello")

    assert result.success is True
    assert result.metadata["sent_id"] == "s1"


@pytest.mark.asyncio
async def test_send_email_tool_propagates_failure():
    fake_service = AsyncMock()
    fake_service.send_message.return_value = EmailResult(success=False, error="rate limited")

    tool = SendEmailTool(email_service=fake_service)
    result = await tool.execute(to="bob@example.com", subject="Hi", body="Hello")

    assert result.success is False
    assert "rate limited" in result.error
