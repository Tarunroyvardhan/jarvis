from unittest.mock import MagicMock, patch

import pytest

from app.integrations.computer_controller import ComputerController
from app.security.path_guard import PathGuard


def _controller(tmp_path, apps=None):
    guard = PathGuard(allowed_roots=[tmp_path])
    return ComputerController(allowed_applications=apps or {"notepad": "notepad.exe"}, path_guard=guard)


def test_open_application_rejects_unknown_name(tmp_path):
    controller = _controller(tmp_path)
    result = controller.open_application("some_random_unlisted_app")

    assert result.success is False
    assert "isn't in the allowed application list" in result.error


def test_open_application_launches_allowed_app(tmp_path):
    controller = _controller(tmp_path, apps={"notepad": "notepad.exe"})

    with patch("app.integrations.computer_controller.subprocess.Popen") as mock_popen:
        result = controller.open_application("notepad")

    assert result.success is True
    mock_popen.assert_called_once_with(["notepad.exe"])


def test_open_application_name_lookup_is_case_insensitive(tmp_path):
    controller = _controller(tmp_path, apps={"notepad": "notepad.exe"})

    with patch("app.integrations.computer_controller.subprocess.Popen"):
        result = controller.open_application("NotePad")

    assert result.success is True


def test_open_application_reports_launch_failure(tmp_path):
    controller = _controller(tmp_path, apps={"notepad": "notepad.exe"})

    with patch("app.integrations.computer_controller.subprocess.Popen", side_effect=OSError("not found")):
        result = controller.open_application("notepad")

    assert result.success is False
    assert "Could not launch" in result.error


def test_open_website_rejects_non_http_url(tmp_path):
    controller = _controller(tmp_path)
    result = controller.open_website("javascript:alert(1)")

    assert result.success is False
    assert "http" in result.error


def test_open_website_success(tmp_path):
    controller = _controller(tmp_path)

    with patch("app.integrations.computer_controller.webbrowser.open", return_value=True) as mock_open:
        result = controller.open_website("https://example.com")

    assert result.success is True
    mock_open.assert_called_once_with("https://example.com")


def test_open_website_no_browser_available(tmp_path):
    controller = _controller(tmp_path)

    with patch("app.integrations.computer_controller.webbrowser.open", return_value=False):
        result = controller.open_website("https://example.com")

    assert result.success is False


def test_open_folder_denies_path_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / "outside_folder_xyz"
    outside.mkdir(exist_ok=True)
    try:
        controller = _controller(tmp_path)
        result = controller.open_folder(str(outside))
        assert result.success is False
    finally:
        import shutil

        shutil.rmtree(outside, ignore_errors=True)


def test_open_folder_success_within_allowed_root(tmp_path):
    subfolder = tmp_path / "sub"
    subfolder.mkdir()
    controller = _controller(tmp_path)

    with patch("app.integrations.computer_controller.subprocess.Popen") as mock_popen:
        result = controller.open_folder(str(subfolder))

    assert result.success is True
    assert mock_popen.called


def test_open_folder_rejects_a_file_not_a_directory(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    controller = _controller(tmp_path)

    result = controller.open_folder(str(file_path))

    assert result.success is False
    assert "not a folder" in result.error


def test_launch_terminal_without_directory(tmp_path):
    controller = _controller(tmp_path)

    with patch("app.integrations.computer_controller.subprocess.Popen") as mock_popen:
        result = controller.launch_terminal()

    assert result.success is True
    assert mock_popen.called


def test_launch_terminal_denies_directory_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / "outside_terminal_xyz"
    outside.mkdir(exist_ok=True)
    try:
        controller = _controller(tmp_path)
        result = controller.launch_terminal(str(outside))
        assert result.success is False
    finally:
        import shutil

        shutil.rmtree(outside, ignore_errors=True)


def test_list_known_applications(tmp_path):
    controller = _controller(tmp_path, apps={"notepad": "notepad.exe", "vscode": "code"})
    assert controller.list_known_applications() == ["notepad", "vscode"]


def test_allowed_app_not_on_path_is_found_the_windows_way(tmp_path, monkeypatch):
    """Regression: 'chrome=chrome.exe' failed with WinError 2 because Chrome
    isn't on PATH; it must be resolved like Windows does (App Paths etc.)."""
    import app.integrations.computer_controller as cc

    controller = _controller(tmp_path) if "_controller" in globals() else None
    if controller is None:
        from app.security.path_guard import PathGuard

        controller = cc.ComputerController({"chrome": "chrome.exe"}, PathGuard([tmp_path]))
    else:
        controller._allowed_applications["chrome"] = "chrome.exe"

    def not_on_path(args, **kwargs):
        raise FileNotFoundError("[WinError 2]")

    launched = []
    monkeypatch.setattr(cc.subprocess, "Popen", not_on_path)
    monkeypatch.setattr(cc.sys, "platform", "win32")
    monkeypatch.setattr(cc, "launch_windows_app", lambda name: launched.append(name) or "C:/chrome.exe")

    result = controller.open_application("chrome")

    assert result.success is True
    assert launched == ["chrome.exe"]


def test_app_finder_prefers_exact_names():
    from app.integrations.app_finder import _best_match

    entries = (("wsl settings", "a"), ("settings", "b"), ("google chrome", "c"), ("chrome remote desktop", "d"))
    assert _best_match("settings", entries) == "b"
    assert _best_match("chrome", entries) == "c"
    assert _best_match("nothing", entries) is None


def test_real_install_path_opens_without_confirmation_but_lookalikes_ask(tmp_path, monkeypatch):
    """Regression: Jarvis passed Chrome's full install path and got a yes/no
    prompt. The registered install path is safe; the same name elsewhere is not."""
    import app.integrations.computer_controller as cc
    from app.security.path_guard import PathGuard
    from app.security.permissions import PermissionLevel
    from app.tools.computer_tools import OpenApplicationTool

    installed = tmp_path / "Program Files" / "chrome.exe"
    installed.parent.mkdir()
    installed.write_text("")
    lookalike = tmp_path / "Downloads" / "chrome.exe"
    lookalike.parent.mkdir()
    lookalike.write_text("")

    monkeypatch.setattr(cc.sys, "platform", "win32")
    monkeypatch.setattr(cc, "find_windows_app", lambda name: str(installed) if name == "chrome" else None)
    tool = OpenApplicationTool(cc.ComputerController({}, PathGuard([tmp_path])))

    assert tool.permission_for(name=str(installed)) == PermissionLevel.LOW_RISK
    assert tool.permission_for(name=str(lookalike)) == PermissionLevel.CONFIRM_REQUIRED
    assert tool.permission_for(name=str(tmp_path / "setup.exe")) == PermissionLevel.CONFIRM_REQUIRED
