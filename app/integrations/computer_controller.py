"""
ComputerController — the only place in this app allowed to launch
external processes or open the browser, and only through a fixed,
allowlisted set of operations. There is no "run this command" method
here on purpose — that's the exact thing the design doc prohibits
("Do NOT give Claude unrestricted shell execution").

Every method takes a name/path/URL and validates it against an allowlist
or PathGuard before doing anything — none of them accept or build a
shell command string from user input.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from app.security.path_guard import PathAccessError, PathGuard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputerActionResult:
    success: bool
    error: str | None = None


class ComputerController:
    def __init__(self, allowed_applications: dict[str, str], path_guard: PathGuard) -> None:
        # name (lowercase) -> executable/command to launch. Only names in
        # this dict can ever be opened — an arbitrary path or exe name
        # from the model is never accepted directly.
        self._allowed_applications = {k.lower(): v for k, v in allowed_applications.items()}
        self._path_guard = path_guard

    def list_known_applications(self) -> list[str]:
        return sorted(self._allowed_applications.keys())

    def open_application(self, name: str) -> ComputerActionResult:
        executable = self._allowed_applications.get(name.lower())
        if executable is None:
            return ComputerActionResult(
                success=False,
                error=(
                    f"'{name}' isn't in the allowed application list. "
                    f"Known applications: {self.list_known_applications()}"
                ),
            )
        try:
            subprocess.Popen([executable])  # noqa: S603 - executable comes only from the allowlist above
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to launch application '%s'", name)
            return ComputerActionResult(success=False, error=f"Could not launch '{name}': {exc}")
        return ComputerActionResult(success=True)

    def open_website(self, url: str) -> ComputerActionResult:
        if not (url.startswith("http://") or url.startswith("https://")):
            return ComputerActionResult(
                success=False, error="URL must start with http:// or https://"
            )
        try:
            opened = webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            return ComputerActionResult(success=False, error=f"Could not open browser: {exc}")
        if not opened:
            return ComputerActionResult(success=False, error="No browser available to open the URL.")
        return ComputerActionResult(success=True)

    def open_folder(self, path: str) -> ComputerActionResult:
        try:
            resolved = self._path_guard.resolve(path, must_exist=True)
        except PathAccessError as exc:
            return ComputerActionResult(success=False, error=str(exc))

        if not resolved.is_dir():
            return ComputerActionResult(success=False, error=f"'{resolved}' is not a folder.")

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(resolved)])  # noqa: S603, S607
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(resolved)])  # noqa: S603, S607
            else:
                subprocess.Popen(["xdg-open", str(resolved)])  # noqa: S603, S607
        except Exception as exc:  # noqa: BLE001
            return ComputerActionResult(success=False, error=f"Could not open folder: {exc}")
        return ComputerActionResult(success=True)

    def launch_terminal(self, directory: str | None = None) -> ComputerActionResult:
        target: Path | None = None
        if directory:
            try:
                target = self._path_guard.resolve(directory, must_exist=True)
            except PathAccessError as exc:
                return ComputerActionResult(success=False, error=str(exc))
            if not target.is_dir():
                return ComputerActionResult(success=False, error=f"'{target}' is not a folder.")

        try:
            if sys.platform == "win32":
                cmd = ["cmd", "/K"] if target is None else ["cmd", "/K", f"cd /d {target}"]
                subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)  # noqa: S603
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(target) if target else "."])  # noqa: S603, S607
            else:
                subprocess.Popen(["x-terminal-emulator"], cwd=str(target) if target else None)  # noqa: S603, S607
        except Exception as exc:  # noqa: BLE001
            return ComputerActionResult(success=False, error=f"Could not launch terminal: {exc}")
        return ComputerActionResult(success=True)
