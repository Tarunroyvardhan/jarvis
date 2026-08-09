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
