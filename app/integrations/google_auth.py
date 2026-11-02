"""
Google OAuth bootstrap for Calendar + Gmail access.

This module is intentionally small and does exactly one untestable thing:
get a valid set of credentials, prompting a real browser login the first
time. Everything else in the calendar/email integration takes an
already-built API resource object as a constructor argument instead of
building one itself — that's what makes CalendarService/EmailService
testable with fake resources. This file is the one seam that can't be
faked, so it's kept as thin as possible.

Google libraries are imported lazily so the rest of the app (and its
tests) don't need google-auth-oauthlib etc. installed unless calendar/
email is actually being used — same pattern as the voice modules.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GoogleAuthError(Exception):
    pass


class GoogleLoginRequired(GoogleAuthError):
    """No usable cached token and interactive sign-in wasn't allowed."""


def get_credentials(credentials_path: Path, token_path: Path, interactive: bool = True):
    """Return valid Google credentials, refreshing or running the OAuth
    browser flow as needed. Caches the resulting token to `token_path` so
    this only prompts a real login once (until the token is revoked or
    expires — tokens for apps in Google's "Testing" mode expire after 7
    days).

    With interactive=False (used at startup) it never opens a browser: it
    raises GoogleLoginRequired instead, so an expired token can't block
    Jarvis from starting while a sign-in page waits in the background.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GoogleAuthError(
            f"Google API dependencies aren't installed: {exc}. "
            'Install with: pip install -e ".[google]"'
        ) from exc

    if not credentials_path.exists():
        raise GoogleAuthError(
            f"credentials.json not found at {credentials_path}. See README for "
            "the Google Cloud setup steps to obtain one."
        )

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stored Google token could not be read (%s); re-authenticating.", exc)
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                logger.info("Google token refresh failed (%s); a new sign-in is needed.", exc)
                creds = None

        if (not creds or not creds.valid) and not interactive:
            raise GoogleLoginRequired("Google sign-in has expired or hasn't been done yet.")

        if not creds or not creds.valid:
            print(
                "Opening a browser window for Google sign-in — grant Jarvis "
                "access to Calendar and Gmail to continue..."
            )
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
                creds = flow.run_local_server(port=0, timeout_seconds=300)
            except Exception as exc:  # noqa: BLE001 - a failed login must not crash startup
                raise GoogleAuthError(f"Google sign-in did not complete: {exc}") from exc
            if creds is None:
                raise GoogleAuthError("Google sign-in timed out or was cancelled.")

        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
        except OSError as exc:
            logger.warning("Could not cache Google token at %s: %s", token_path, exc)

    return creds


def build_calendar_resource(credentials):
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=credentials)


def build_gmail_resource(credentials):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=credentials)
