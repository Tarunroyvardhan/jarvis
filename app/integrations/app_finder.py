"""
Find an installed Windows application from a friendly name ("chrome",
"word", "spotify", "vs code") and launch it.

Most apps are NOT on PATH, so running "chrome.exe" as a bare command
fails. Windows itself finds apps through several other registries; this
module checks them in order:

  1. App Paths registry (chrome.exe, winword.exe, excel.exe, ...)
  2. PATH (notepad, calc, code, ...)
  3. Start Menu shortcuts (nearly every installed desktop app)
  4. Microsoft Store / packaged apps (Spotify, WhatsApp, Settings, ...)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Friendly names people say -> the executable Windows registers.
ALIASES = {
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "google chrome": "chrome",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "file explorer": "explorer",
    "calculator": "calc",
    "paint": "mspaint",
    "command prompt": "cmd",
    "task manager": "taskmgr",
}


def _normalise(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\.exe$", "", name)
    return ALIASES.get(name, name)


def _app_paths_lookup(exe_stem: str) -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    key = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_stem}.exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value = winreg.QueryValue(handle, None).strip().strip('"')
                if value and Path(os.path.expandvars(value)).exists():
                    return os.path.expandvars(value)
        except OSError:
            continue
    return None


def _start_menu_dirs() -> list[Path]:
    dirs = []
    for env in ("ProgramData", "APPDATA"):
        base = os.environ.get(env)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=1)
def _start_menu_shortcuts() -> tuple[tuple[str, str], ...]:
    found = []
    for root in _start_menu_dirs():
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if "uninstall" in stem or "readme" in stem or "help" in stem:
                continue
            found.append((stem, str(lnk)))
    return tuple(found)


@lru_cache(maxsize=1)
def _store_apps() -> tuple[tuple[str, str], ...]:
    """(name, AppID) for every app in the Start menu, including Store apps."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(out.stdout.decode("utf-8", errors="replace") or "[]")
    except Exception:  # noqa: BLE001
        logger.debug("Get-StartApps failed", exc_info=True)
        return ()
    if isinstance(data, dict):
        data = [data]
    return tuple((str(d.get("Name", "")).lower(), str(d.get("AppID", ""))) for d in data if d.get("AppID"))


def _best_match(query: str, entries: tuple[tuple[str, str], ...]) -> str | None:
    """Exact name first, then 'starts with', then 'contains' (shortest wins,
    so 'chrome' picks 'Google Chrome' over 'Chrome Remote Desktop')."""
    exact = [v for n, v in entries if n == query]
    if exact:
        return exact[0]
    words = [(n, v) for n, v in entries if re.search(rf"\b{re.escape(query)}\b", n)]
    if words:
        return min(words, key=lambda nv: len(nv[0]))[1]
    contains = [(n, v) for n, v in entries if query in n]
    if contains:
        return min(contains, key=lambda nv: len(nv[0]))[1]
    return None


def find_windows_app(name: str) -> str | None:
    """Return something os.startfile() can launch: an .exe/.lnk path, or
    'shell:AppsFolder\\<AppID>' for Store apps. None if nothing matches."""
    query = _normalise(name)
    if not query:
        return None
    for candidate in dict.fromkeys([query, name.strip().lower()]):
        # PATH first: for built-ins like notepad it gives the launchable
        # System32 stub, whereas App Paths points into the protected
        # WindowsApps folder, which can't be started directly.
        on_path = shutil.which(candidate)
        if on_path and on_path.lower().endswith((".cmd", ".bat")):
            # e.g. VS Code's code.cmd: prefer the real .exe (no console flash).
            path = _app_paths_lookup(candidate) or _app_paths_lookup(Path(on_path).stem) or on_path
        else:
            path = on_path or _app_paths_lookup(candidate)
        if path:
            return path

    friendly = name.strip().lower()
    candidates = list(dict.fromkeys([friendly, query]))
    shortcuts = _start_menu_shortcuts()
    # Exact names anywhere beat partial matches: "settings" must open
    # Windows Settings (a Store app), not the "WSL Settings" shortcut.
    for candidate in candidates:
        exact = [v for n, v in shortcuts if n == candidate]
        if exact:
            return exact[0]
        exact_ids = [v for n, v in _store_apps() if n == candidate]
        if exact_ids:
            return f"shell:AppsFolder\\{exact_ids[0]}"
    for candidate in candidates:
        match = _best_match(candidate, shortcuts)
        if match:
            return match
        app_id = _best_match(candidate, _store_apps())
        if app_id:
            return f"shell:AppsFolder\\{app_id}"
    return None


def launch_windows_app(name: str) -> str:
    """Find and launch `name`. Returns what was launched; raises
    FileNotFoundError if the app can't be found."""
    target = find_windows_app(name)
    if target is None:
        raise FileNotFoundError(f"Couldn't find an installed app called '{name}'.")
    if target.lower().endswith(".exe"):
        try:
            subprocess.Popen([target], close_fds=True)  # noqa: S603 - resolved installed program
        except PermissionError:
            os.startfile(target)  # noqa: S606 - packaged apps need ShellExecute
    else:
        os.startfile(target)  # noqa: S606 - .lnk / .cmd / Store app via ShellExecute
    return target


def is_windows() -> bool:
    return sys.platform == "win32"
