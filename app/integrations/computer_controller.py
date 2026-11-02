"""
ComputerController — the only place in this app allowed to launch
external processes or open the browser, and only through a fixed,
allowlisted set of operations. There is no "run this command" method
here on purpose — that's the exact thing the design doc prohibits
("Do NOT give Claude unrestricted shell execution").

Every method takes a name/path/URL and validates it against an allowlist
or PathGuard before doing anything — none of them accept or build a
shell command string from user input. The one exception to the
application allowlist, `launch_unlisted`, is only reachable through a
confirmation-gated tool call and uses ShellExecute (no shell parsing).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from app.integrations.app_finder import find_windows_app, launch_windows_app
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

    def is_allowed(self, name: str) -> bool:
        return name.lower().strip() in self._allowed_applications

    def is_installed_app_path(self, path: str) -> bool:
        """True if `path` is exactly the program Windows itself launches for
        that app name (e.g. C:\\Program Files\\Google\\Chrome\\...\\chrome.exe
        for "chrome"). A random setup.exe in Downloads is not, because
        Windows has no app registered under its name at that location."""
        if sys.platform != "win32" or not path.strip():
            return False
        candidate = Path(path.strip().strip('"'))
        if candidate.suffix.lower() != ".exe" or not candidate.is_absolute():
            return False
        try:
            registered = find_windows_app(candidate.stem)
        except Exception:  # noqa: BLE001 - when unsure, ask
            return False
        if not registered:
            return False
        try:
            return Path(registered).resolve() == candidate.resolve()
        except OSError:
            return False

    def launch_unlisted(self, name: str) -> ComputerActionResult:
        """Open something not on the allowlist — an app registered with
        Windows ("chrome", "excel", "spotify"), a URI ("ms-settings:"), or
        an executable path. Callers must have obtained user confirmation;
        the tool layer enforces that.
        """
        target = name.strip()
        if not target:
            return ComputerActionResult(success=False, error="No application name given.")
        try:
            if sys.platform == "win32":
                if target.endswith(":") or "\\" in target or "/" in target:
                    os.startfile(target)  # noqa: S606 - URI ("ms-settings:") or path; ShellExecute
                else:
                    launch_windows_app(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", target])  # noqa: S603, S607
            else:
                subprocess.Popen([target])  # noqa: S603
        except Exception as exc:  # noqa: BLE001
            return ComputerActionResult(
                success=False,
                error=f"Could not launch '{target}': {exc}",
            )
        return ComputerActionResult(success=True)

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
        except FileNotFoundError:
            # Most apps (Chrome, Word, Spotify...) aren't on PATH; find them
            # the way Windows does (App Paths, Start Menu, Store apps).
            if sys.platform != "win32":
                return ComputerActionResult(success=False, error=f"Could not find '{executable}'.")
            try:
                launch_windows_app(executable)
            except FileNotFoundError:
                try:
                    launch_windows_app(name)
                except Exception as exc:  # noqa: BLE001
                    return ComputerActionResult(success=False, error=f"Could not launch '{name}': {exc}")
            except Exception as exc:  # noqa: BLE001
                return ComputerActionResult(success=False, error=f"Could not launch '{name}': {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to launch application '%s': %s", name, exc)
            return ComputerActionResult(success=False, error=f"Could not launch '{name}': {exc}")
        return ComputerActionResult(success=True)

    def open_website(self, url: str) -> ComputerActionResult:
        url = url.strip()
        if "://" not in url and "." in url and " " not in url and not url.lower().startswith("javascript:"):
            url = "https://" + url  # "youtube.com" -> "https://youtube.com"
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
                # cwd= instead of building a "cd" command string, so odd
                # characters in a folder name can't be interpreted by cmd.
                subprocess.Popen(  # noqa: S603, S607
                    ["powershell.exe", "-NoExit"],
                    cwd=str(target) if target else None,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(target) if target else "."])  # noqa: S603, S607
            else:
                subprocess.Popen(["x-terminal-emulator"], cwd=str(target) if target else None)  # noqa: S603, S607
        except Exception as exc:  # noqa: BLE001
            return ComputerActionResult(success=False, error=f"Could not launch terminal: {exc}")
        return ComputerActionResult(success=True)
