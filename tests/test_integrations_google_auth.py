import sys
from pathlib import Path

import pytest

from app.integrations.google_auth import GoogleAuthError, get_credentials


def test_get_credentials_reports_missing_credentials_file(tmp_path):
    """This is the one piece of this integration I can fully verify myself
    — no real Google account or browser needed. The interactive OAuth
    consent flow itself (when credentials.json IS present and valid)
    can't be exercised in this environment and needs manual verification
    on a real machine with a real browser."""
    missing_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"

    with pytest.raises(GoogleAuthError) as exc_info:
        get_credentials(missing_path, token_path)

    assert "credentials.json not found" in str(exc_info.value)


def test_get_credentials_reports_missing_dependency(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", None)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", None)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", None)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", None)

    # Even with a credentials.json present, missing the library itself
    # should be reported clearly rather than raising a raw ImportError.
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text("{}")

    with pytest.raises(GoogleAuthError) as exc_info:
        get_credentials(creds_path, tmp_path / "token.json")

    assert "Google API dependencies aren't installed" in str(exc_info.value)
