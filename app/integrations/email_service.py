"""
Gmail integration.

EmailService, like CalendarService, takes an already-built Gmail API
resource object rather than constructing one itself, for the same
testability reason.

Sending always goes through the draft-then-send-draft path even for
`send_message` on its own — the tool layer decides whether that draft
gets sent immediately (behind a Level 3 confirmation) or left as a
Level 1 draft only.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSummary:
    id: str
    subject: str
    sender: str
    snippet: str
    date: str


@dataclass(frozen=True)
class EmailMessage:
    id: str
    subject: str
    sender: str
    date: str
    body: str


@dataclass(frozen=True)
class EmailResult:
    success: bool
    messages: list[EmailSummary] = field(default_factory=list)
    message: EmailMessage | None = None
    draft_id: str | None = None
    sent_id: str | None = None
    error: str | None = None


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
    for part in payload.get("parts") or []:
        nested = _extract_body(part)
        if nested:
            return nested
    return ""


def _build_mime(to: str, subject: str, body: str) -> dict:
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


class EmailService:
    def __init__(self, resource) -> None:
        self._resource = resource

    async def search_messages(self, query: str, max_results: int = 10) -> EmailResult:
        try:
            list_response = await asyncio.to_thread(
                lambda: self._resource.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to search email")
            return EmailResult(success=False, error=str(exc))

        message_ids = [m["id"] for m in list_response.get("messages", [])]
        summaries = []
        try:
            for message_id in message_ids:
                meta = await asyncio.to_thread(
                    lambda mid=message_id: self._resource.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                headers = meta.get("payload", {}).get("headers", [])
                summaries.append(
                    EmailSummary(
                        id=message_id,
                        subject=_header(headers, "Subject") or "(no subject)",
                        sender=_header(headers, "From"),
                        snippet=meta.get("snippet", ""),
                        date=_header(headers, "Date"),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to fetch email metadata")
            return EmailResult(success=False, error=str(exc))

        return EmailResult(success=True, messages=summaries)

    async def read_message(self, message_id: str) -> EmailResult:
        try:
            msg = await asyncio.to_thread(
                lambda: self._resource.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to read email")
            return EmailResult(success=False, error=str(exc))

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        return EmailResult(
            success=True,
            message=EmailMessage(
                id=message_id,
                subject=_header(headers, "Subject") or "(no subject)",
                sender=_header(headers, "From"),
                date=_header(headers, "Date"),
                body=_extract_body(payload),
            ),
        )

    async def create_draft(self, to: str, subject: str, body: str) -> EmailResult:
        if not to or not to.strip():
            return EmailResult(success=False, error="Recipient (to) cannot be empty.")

        try:
            mime = _build_mime(to, subject, body)
            draft = await asyncio.to_thread(
                lambda: self._resource.users()
                .drafts()
                .create(userId="me", body={"message": mime})
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to create draft")
            return EmailResult(success=False, error=str(exc))

        return EmailResult(success=True, draft_id=draft.get("id"))

    async def send_message(self, to: str, subject: str, body: str) -> EmailResult:
        if not to or not to.strip():
            return EmailResult(success=False, error="Recipient (to) cannot be empty.")

        try:
            mime = _build_mime(to, subject, body)
            sent = await asyncio.to_thread(
                lambda: self._resource.users().messages().send(userId="me", body=mime).execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to send email")
            return EmailResult(success=False, error=str(exc))

        return EmailResult(success=True, sent_id=sent.get("id"))
