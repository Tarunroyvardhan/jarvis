from __future__ import annotations

from typing import Any

from app.integrations.email_service import EmailService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class SearchEmailTool(Tool):
    name = "search_email"
    description = "Search email using Gmail search syntax (e.g. 'from:someone', 'subject:invoice', 'is:unread')."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="query", type="string", description="Gmail search query."),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of results.",
            required=False,
        ),
    ]

    def __init__(self, email_service: EmailService) -> None:
        self._service = email_service

    async def execute(self, query: str, max_results: int = 10, **kwargs: Any) -> ToolResult:
        result = await self._service.search_messages(query=query, max_results=max_results)
        if not result.success:
            return ToolResult(success=False, error=result.error)

        messages = [
            {"id": m.id, "subject": m.subject, "from": m.sender, "date": m.date, "snippet": m.snippet}
            for m in result.messages
        ]
        return ToolResult(success=True, result=messages, metadata={"count": len(messages)})


class ReadEmailTool(Tool):
    name = "read_email"
    description = "Read the full content of a specific email by its id (from search_email results)."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(name="message_id", type="string", description="Id of the email to read."),
    ]

    def __init__(self, email_service: EmailService) -> None:
        self._service = email_service

    async def execute(self, message_id: str, **kwargs: Any) -> ToolResult:
        result = await self._service.read_message(message_id)
        if not result.success:
            return ToolResult(success=False, error=result.error)

        m = result.message
        return ToolResult(
            success=True,
            result={"subject": m.subject, "from": m.sender, "date": m.date, "body": m.body},
        )


class DraftEmailTool(Tool):
    name = "draft_email"
    description = (
        "Create an email draft without sending it. Low risk — nothing is sent, "
        "no confirmation needed."
    )
    permission_level = PermissionLevel.LOW_RISK
    parameters = [
        ToolParameter(name="to", type="string", description="Recipient email address."),
        ToolParameter(name="subject", type="string", description="Email subject."),
        ToolParameter(name="body", type="string", description="Email body text."),
    ]

    def __init__(self, email_service: EmailService) -> None:
        self._service = email_service

    async def execute(self, to: str, subject: str, body: str, **kwargs: Any) -> ToolResult:
        result = await self._service.create_draft(to=to, subject=subject, body=body)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(
            success=True,
            result=f"Draft created (id={result.draft_id}). Not sent.",
            metadata={"draft_id": result.draft_id},
        )


class SendEmailTool(Tool):
    name = "send_email"
    description = (
        "Send an email immediately. Always requires explicit user confirmation "
        "before sending — prepare the content, then call this, and the user "
        "will be asked to approve before anything is actually sent."
    )
    permission_level = PermissionLevel.ALWAYS_CONFIRM
    parameters = [
        ToolParameter(name="to", type="string", description="Recipient email address."),
        ToolParameter(name="subject", type="string", description="Email subject."),
        ToolParameter(name="body", type="string", description="Email body text."),
    ]

    def __init__(self, email_service: EmailService) -> None:
        self._service = email_service

    async def describe(
        self, to: str = "", subject: str = "", body: str = "", **kwargs: Any
    ) -> str:
        # Show the whole message: the user is approving exactly what goes out.
        preview = body if len(body) <= 3000 else body[:3000] + f"\n[... {len(body) - 3000} more characters]"
        return f'Send email to {to}, subject "{subject}":\n---\n{preview}\n---'

    async def execute(self, to: str, subject: str, body: str, **kwargs: Any) -> ToolResult:
        result = await self._service.send_message(to=to, subject=subject, body=body)
        if not result.success:
            return ToolResult(success=False, error=result.error)
        return ToolResult(
            success=True,
            result=f"Email sent to {to}.",
            metadata={"sent_id": result.sent_id},
        )
