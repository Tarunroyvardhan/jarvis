import base64
from unittest.mock import MagicMock

import pytest

from app.integrations.email_service import EmailService


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _fake_gmail_resource(list_response=None, get_responses=None, execute_side_effect=None):
    """Mimics resource.users().messages()/.drafts() fluent chains."""
    resource = MagicMock()
    users = resource.users.return_value
    messages = users.messages.return_value
    drafts = users.drafts.return_value

    if execute_side_effect is not None:
        messages.list.return_value.execute.side_effect = execute_side_effect
    else:
        messages.list.return_value.execute.return_value = list_response or {}

    if get_responses is not None:
        messages.get.return_value.execute.side_effect = get_responses

    return resource, messages, drafts


@pytest.mark.asyncio
async def test_search_messages_returns_summaries():
    list_response = {"messages": [{"id": "m1"}, {"id": "m2"}]}
    get_responses = [
        {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Date", "value": "Mon, 10 Aug 2026 09:00:00"},
                ]
            },
            "snippet": "Hi there...",
        },
        {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Invoice"},
                    {"name": "From", "value": "billing@example.com"},
                    {"name": "Date", "value": "Tue, 11 Aug 2026 09:00:00"},
                ]
            },
            "snippet": "Your invoice...",
        },
    ]
    resource, _, _ = _fake_gmail_resource(list_response=list_response, get_responses=get_responses)
    service = EmailService(resource)

    result = await service.search_messages(query="test")

    assert result.success is True
    assert len(result.messages) == 2
    assert result.messages[0].subject == "Hello"
    assert result.messages[0].sender == "alice@example.com"


@pytest.mark.asyncio
async def test_search_messages_no_results():
    resource, _, _ = _fake_gmail_resource(list_response={})
    service = EmailService(resource)

    result = await service.search_messages(query="nonexistent")

    assert result.success is True
    assert result.messages == []


@pytest.mark.asyncio
async def test_search_messages_reports_api_error():
    resource, _, _ = _fake_gmail_resource(execute_side_effect=RuntimeError("auth expired"))
    service = EmailService(resource)

    result = await service.search_messages(query="test")

    assert result.success is False
    assert "auth expired" in result.error


@pytest.mark.asyncio
async def test_read_message_extracts_plain_text_body():
    body_text = "Hello, this is the email body."
    api_response = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test Subject"},
                {"name": "From", "value": "bob@example.com"},
                {"name": "Date", "value": "Mon, 10 Aug 2026 09:00:00"},
            ],
            "body": {"data": _b64(body_text)},
        }
    }
    resource = MagicMock()
    resource.users.return_value.messages.return_value.get.return_value.execute.return_value = api_response
    service = EmailService(resource)

    result = await service.read_message("m1")

    assert result.success is True
    assert result.message.subject == "Test Subject"
    assert result.message.body == body_text


@pytest.mark.asyncio
async def test_read_message_extracts_body_from_multipart():
    body_text = "Plain text part."
    api_response = {
        "payload": {
            "headers": [{"name": "Subject", "value": "Multipart"}],
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64(body_text)}},
            ],
        }
    }
    resource = MagicMock()
    resource.users.return_value.messages.return_value.get.return_value.execute.return_value = api_response
    service = EmailService(resource)

    result = await service.read_message("m1")

    assert result.success is True
    assert result.message.body == body_text


@pytest.mark.asyncio
async def test_read_message_reports_error():
    resource = MagicMock()
    resource.users.return_value.messages.return_value.get.return_value.execute.side_effect = RuntimeError(
        "message not found"
    )
    service = EmailService(resource)

    result = await service.read_message("nonexistent")

    assert result.success is False
    assert "message not found" in result.error


@pytest.mark.asyncio
async def test_create_draft_rejects_empty_recipient():
    resource = MagicMock()
    service = EmailService(resource)

    result = await service.create_draft(to="  ", subject="Hi", body="Hello")

    assert result.success is False
    assert "Recipient" in result.error


@pytest.mark.asyncio
async def test_create_draft_success():
    resource = MagicMock()
    resource.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft123"
    }
    service = EmailService(resource)

    result = await service.create_draft(to="alice@example.com", subject="Hi", body="Hello there")

    assert result.success is True
    assert result.draft_id == "draft123"


@pytest.mark.asyncio
async def test_send_message_rejects_empty_recipient():
    resource = MagicMock()
    service = EmailService(resource)

    result = await service.send_message(to="", subject="Hi", body="Hello")

    assert result.success is False
    assert "Recipient" in result.error


@pytest.mark.asyncio
async def test_send_message_success():
    resource = MagicMock()
    resource.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent456"
    }
    service = EmailService(resource)

    result = await service.send_message(to="bob@example.com", subject="Hi", body="Hello")

    assert result.success is True
    assert result.sent_id == "sent456"


@pytest.mark.asyncio
async def test_send_message_reports_error():
    resource = MagicMock()
    resource.users.return_value.messages.return_value.send.return_value.execute.side_effect = RuntimeError(
        "quota exceeded"
    )
    service = EmailService(resource)

    result = await service.send_message(to="bob@example.com", subject="Hi", body="Hello")

    assert result.success is False
    assert "quota exceeded" in result.error
