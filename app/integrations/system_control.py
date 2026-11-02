"""
System-level access: shell commands, system status, processes, screen
capture, clipboard, media keys and desktop notifications.

Risk is handled at the tool layer, not here: run_shell_command and
kill_process are confirmation-gated tools, so the user sees the exact
command/process before anything happens. This module just does the work
reliably — bounded output, hard timeouts that actually kill the child
process, and no shell-string building from model input except for the
one place that is *meant* to run a shell command.

Optional dependencies: psutil (richer system info/processes) and Pillow
(screenshots), both in the `system` extra. Everything degrades to a
clear error message when they're missing.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
MAX_OUTPUT_CHARS = 30_000
SCREENSHOT_MAX_SIDE = 1568  # keeps the image within the model's preferred size


@dataclass(frozen=True)
class ProcessOutput:
    success: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    def as_text(self) -> str:
        parts = [f"exit code: {self.exit_code}"]
        if self.stdout.strip():
            parts.append("stdout:\n" + _clip(self.stdout))
        if self.stderr.strip():
            parts.append("stderr:\n" + _clip(self.stderr))
        if len(parts) == 1:
            parts.append("(no output)")
        return "\n".join(parts)


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT_CHARS} characters omitted] ...\n{text[-half:]}"


async def run_process(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: float = 60,
    stdin_text: str | None = None,
) -> ProcessOutput:
    """Run a process without a shell, with a timeout that really kills it."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ProcessOutput(success=False, error=f"Program not found: {args[0]}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to start %s", args[0])
        return ProcessOutput(success=False, error=f"Could not start {args[0]}: {exc}")

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_text.encode("utf-8") if stdin_text is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        _kill_tree(process.pid)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        return ProcessOutput(success=False, error=f"Timed out after {timeout:.0f}s and was stopped.")

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    return ProcessOutput(success=process.returncode == 0, exit_code=process.returncode, stdout=out, stderr=err)


def _kill_tree(pid: int) -> None:
    """Kill a process and its children (a timed-out PowerShell may have
    spawned its own children that would otherwise linger)."""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.kill(pid, 9)
    except Exception:  # noqa: BLE001
        logger.warning("Could not kill process %s", pid, exc_info=True)


def shell_argv(command: str) -> list[str]:
    if IS_WINDOWS:
        # Force UTF-8 output so non-ASCII text survives the round trip.
        prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; "
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + command]
    return ["/bin/bash", "-lc", command]


async def run_shell(command: str, cwd: str | None = None, timeout: float = 120) -> ProcessOutput:
    if cwd and not Path(cwd).is_dir():
        return ProcessOutput(success=False, error=f"Working directory does not exist: {cwd}")
    return await run_process(shell_argv(command), cwd=cwd, timeout=timeout)


# --- System information -------------------------------------------------


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def system_info() -> dict:
    info: dict = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.node(),
        "python": platform.python_version(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        import psutil
    except ImportError:
        disks = {}
        for root in _drive_roots():
            try:
                usage = shutil.disk_usage(root)
                disks[root] = f"{_fmt_bytes(usage.free)} free of {_fmt_bytes(usage.total)}"
            except OSError:
                continue
        info["disks"] = disks
        info["note"] = "Install psutil (pip install -e \".[system]\") for CPU, memory, battery and process details."
        return info

    vm = psutil.virtual_memory()
    info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    info["cpu_cores"] = psutil.cpu_count()
    info["memory"] = f"{_fmt_bytes(vm.used)} used of {_fmt_bytes(vm.total)} ({vm.percent}%)"
    info["uptime"] = str(timedelta(seconds=int(time.time() - psutil.boot_time())))
    disks = {}
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks[part.mountpoint] = f"{_fmt_bytes(usage.free)} free of {_fmt_bytes(usage.total)} ({usage.percent}% used)"
    info["disks"] = disks
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery is not None:
        info["battery"] = f"{battery.percent:.0f}% ({'charging' if battery.power_plugged else 'on battery'})"
    info["top_memory_processes"] = [
        f"{p['name']} (pid {p['pid']}): {_fmt_bytes(p['memory'])}" for p in list_processes(limit=8)
    ]
    return info


def _drive_roots() -> list[str]:
    if IS_WINDOWS:
        return [f"{letter}:\\" for letter in "CDEFGH" if os.path.exists(f"{letter}:\\")]
    return ["/"]


def list_processes(name_filter: str | None = None, limit: int = 25) -> list[dict]:
    import psutil

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = p.info["name"] or ""
            if name_filter and name_filter.lower() not in name.lower():
                continue
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
            procs.append({"pid": p.info["pid"], "name": name, "memory": mem})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda d: d["memory"], reverse=True)
    return procs[:limit]


def terminate_process(pid: int) -> str:
    import psutil

    proc = psutil.Process(pid)
    name = proc.name()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        proc.kill()
    return f"Stopped {name} (pid {pid})."


def process_name(pid: int) -> str | None:
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        return None


# --- Screen, clipboard, media, notifications -----------------------------


def capture_screenshot() -> tuple[dict, str]:
    """Return (image content block, short description) of all screens."""
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError("Pillow is not installed. Install with: pip install -e \".[system]\"") from exc

    image = ImageGrab.grab(all_screens=True)
    original = image.size
    image.thumbnail((SCREENSHOT_MAX_SIDE, SCREENSHOT_MAX_SIDE))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=80)
    block = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buffer.getvalue()).decode("ascii"),
        },
    }
    return block, f"Screenshot captured ({original[0]}x{original[1]}, scaled to {image.size[0]}x{image.size[1]})."


async def get_clipboard() -> str:
    if not IS_WINDOWS:
        raise RuntimeError("Clipboard access is only implemented on Windows.")
    out = await run_process(shell_argv("Get-Clipboard -Raw"), timeout=15)
    if out.error:
        raise RuntimeError(out.error)
    return out.stdout.rstrip("\r\n")


async def set_clipboard(text: str) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Clipboard access is only implemented on Windows.")
    # Text goes through stdin, never into the command string.
    script = "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"
    out = await run_process(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=15, stdin_text=text
    )
    if not out.success:
        raise RuntimeError(out.error or out.stderr or "Set-Clipboard failed")


MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next_track": 0xB0,
    "previous_track": 0xB1,
    "stop": 0xB2,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}


def press_media_key(action: str, times: int = 1) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Media keys are only implemented on Windows.")
    import ctypes

    vk = MEDIA_KEYS[action]
    keyup = 0x0002
    for _ in range(max(1, min(times, 50))):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, keyup, 0)
        time.sleep(0.02)


def lock_workstation() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Locking the screen is only implemented on Windows.")
    import ctypes

    if not ctypes.windll.user32.LockWorkStation():
        raise RuntimeError("LockWorkStation failed.")


_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName('text')
$texts.Item(0).AppendChild($template.CreateTextNode($env:JARVIS_TOAST_TITLE)) > $null
$texts.Item(1).AppendChild($template.CreateTextNode($env:JARVIS_TOAST_BODY)) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


def show_desktop_notification(title: str, body: str) -> bool:
    """Fire-and-forget Windows toast. Title/body travel via environment
    variables so no text is ever interpolated into the script. Returns
    False (never raises) when notifications aren't available."""
    if not IS_WINDOWS:
        return False
    env = dict(os.environ, JARVIS_TOAST_TITLE=title[:120], JARVIS_TOAST_BODY=body[:500])
    try:
        subprocess.Popen(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _TOAST_SCRIPT],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("Desktop notification failed", exc_info=True)
        return False
