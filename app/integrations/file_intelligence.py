"""
File intelligence — find, read, search, list, write, copy, move and
(with confirmation) delete files, all restricted to configured allowed
directories via PathGuard. No operation here ever touches a path outside
those roots.

All methods are synchronous (plain filesystem work); the tool layer runs
them in a worker thread so a big directory walk never freezes the event
loop (and with it the reminder scheduler).

PDF/DOCX text extraction uses pypdf/python-docx if installed (the
`files` extra); if not installed, reading those formats fails with a
clear message rather than a raw ImportError.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.security.path_guard import PathAccessError, PathGuard

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".csv",
    ".html", ".htm", ".css", ".xml", ".log", ".ini", ".cfg", ".toml", ".bat", ".ps1",
    ".sh", ".sql", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb", ".php",
    ".env.example", ".gitignore", ".rst", ".tex",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".mp3", ".wav", ".flac",
    ".mp4", ".mkv", ".avi", ".mov", ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".dll", ".msi",
    ".iso", ".bin", ".db", ".sqlite", ".sqlite3", ".pyc", ".xlsx", ".xls", ".pptx", ".ppt", ".doc",
}

# Directories that are never worth walking: huge, generated, or internal.
SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", "dist", "build", ".next", ".cache", "$RECYCLE.BIN",
    "System Volume Information", "site-packages",
}

# Stop walking after this many files so one enormous folder can't hang a request.
MAX_FILES_SCANNED = 50_000
# Files larger than this are skipped by content search.
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class FileEntry:
    path: str
    name: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class FileResult:
    success: bool
    files: list[FileEntry] = field(default_factory=list)
    content: str | None = None
    matches: list[dict] = field(default_factory=list)
    error: str | None = None


def _walk_files(root: Path) -> Iterator[Path]:
    """Yield files under root, pruning SKIP_DIR_NAMES, never following
    directory symlinks (which could lead outside the allowed root), and
    ignoring folders we aren't permitted to read."""
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=lambda _e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            scanned += 1
            if scanned > MAX_FILES_SCANNED:
                return
            yield Path(dirpath) / name


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or not path.suffix


class FileIntelligenceService:
    def __init__(self, path_guard: PathGuard) -> None:
        self._guard = path_guard

    def _entry(self, path: Path) -> FileEntry:
        stat = path.stat()
        return FileEntry(
            path=str(path),
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        )

    def _roots(self, directory: str | None) -> list[Path]:
        if directory:
            root = self._guard.resolve(directory, must_exist=True)
            if not root.is_dir():
                raise PathAccessError(f"'{root}' is not a folder.")
            return [root]
        return self._guard.allowed_roots

    def find_files(self, query: str, directory: str | None = None, limit: int = 20) -> FileResult:
        try:
            roots = self._roots(directory)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        query_lower = query.lower().strip()
        matches: list[FileEntry] = []
        for search_root in roots:
            for path in _walk_files(search_root):
                if query_lower in path.name.lower():
                    try:
                        matches.append(self._entry(path))
                    except OSError:
                        continue
                    if len(matches) >= limit:
                        return FileResult(success=True, files=matches)
        return FileResult(success=True, files=matches)

    def list_recent_files(self, directory: str | None = None, limit: int = 10) -> FileResult:
        try:
            roots = self._roots(directory)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        stamped: list[tuple[float, Path]] = []
        for search_root in roots:
            for path in _walk_files(search_root):
                try:
                    stamped.append((path.stat().st_mtime, path))
                except OSError:
                    continue

        stamped.sort(key=lambda pair: pair[0], reverse=True)
        entries = []
        for _, path in stamped[:limit]:
            try:
                entries.append(self._entry(path))
            except OSError:
                continue
        return FileResult(success=True, files=entries)

    def list_directory(self, directory: str) -> FileResult:
        try:
            root = self._guard.resolve(directory, must_exist=True)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))
        if not root.is_dir():
            return FileResult(success=False, error=f"'{root}' is not a folder.")
        lines = []
        try:
            children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            return FileResult(success=False, error=f"Could not list '{root}': {exc}")
        for child in children[:500]:
            try:
                if child.is_dir():
                    lines.append(f"[dir]  {child.name}")
                else:
                    lines.append(f"       {child.name}  ({child.stat().st_size} bytes)")
            except OSError:
                continue
        if len(children) > 500:
            lines.append(f"... and {len(children) - 500} more")
        return FileResult(success=True, content="\n".join(lines) or "(empty folder)")

    def read_file(self, path: str) -> FileResult:
        try:
            resolved = self._guard.resolve(path, must_exist=True)
            if not resolved.is_file():
                return FileResult(success=False, error=f"'{resolved}' is not a file.")
            self._guard.check_readable_size(resolved)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        suffix = resolved.suffix.lower()
        try:
            if suffix == ".pdf":
                content = self._read_pdf(resolved)
            elif suffix == ".docx":
                content = self._read_docx(resolved)
            elif suffix in BINARY_EXTENSIONS:
                return FileResult(
                    success=False,
                    error=f"Unsupported file type '{suffix}'. Supported: text files, .pdf, .docx",
                )
            elif _is_text_file(resolved):
                content = resolved.read_text(encoding="utf-8", errors="replace")
            else:
                # Unknown extension: read it if it looks like text.
                raw = resolved.read_bytes()
                if b"\x00" in raw[:8192]:
                    return FileResult(
                        success=False,
                        error=f"'{resolved.name}' looks like a binary file; only text, .pdf and .docx can be read.",
                    )
                content = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to read file %s", resolved)
            return FileResult(success=False, error=f"Could not read '{resolved}': {exc}")

        return FileResult(success=True, content=content)

    def _read_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                f"pypdf is not installed: {exc}. Install with: pip install -e \".[files]\""
            ) from exc
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def _read_docx(self, path: Path) -> str:
        try:
            import docx
        except ImportError as exc:
            raise RuntimeError(
                f"python-docx is not installed: {exc}. Install with: pip install -e \".[files]\""
            ) from exc
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)

    def search_file_contents(
        self, query: str, directory: str | None = None, limit: int = 20
    ) -> FileResult:
        try:
            roots = self._roots(directory)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        query_lower = query.lower()
        matches: list[dict] = []

        for search_root in roots:
            for path in _walk_files(search_root):
                if path.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                try:
                    if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query_lower in line.lower():
                        matches.append(
                            {"path": str(path), "line": line_number, "text": line.strip()[:300]}
                        )
                        if len(matches) >= limit:
                            return FileResult(success=True, matches=matches)

        return FileResult(success=True, matches=matches)

    def file_exists(self, path: str) -> bool:
        try:
            return self._guard.resolve(path, must_exist=False).exists()
        except PathAccessError:
            return False

    def write_file(self, path: str, content: str, append: bool = False) -> FileResult:
        try:
            resolved = self._guard.resolve(path, must_exist=False)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))
        if resolved.is_dir():
            return FileResult(success=False, error=f"'{resolved}' is a folder, not a file.")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            return FileResult(success=False, error="Content is too large to write in one go (5MB limit).")
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "a" if append else "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
        except OSError as exc:
            return FileResult(success=False, error=f"Could not write '{resolved}': {exc}")
        verb = "Appended" if append else "Wrote"
        return FileResult(success=True, content=f"{verb} {len(data)} bytes to {resolved}")

    def create_folder(self, path: str) -> FileResult:
        try:
            resolved = self._guard.resolve(path, must_exist=False)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return FileResult(success=False, error=f"Could not create '{resolved}': {exc}")
        return FileResult(success=True, content=f"Folder ready: {resolved}")

    def copy_path(self, source: str, destination: str) -> FileResult:
        return self._transfer(source, destination, move=False)

    def move_path(self, source: str, destination: str) -> FileResult:
        return self._transfer(source, destination, move=True)

    def _transfer(self, source: str, destination: str, move: bool) -> FileResult:
        try:
            src = self._guard.resolve(source, must_exist=True)
            dst = self._guard.resolve(destination, must_exist=False)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))
        if src in self._guard.allowed_roots:
            return FileResult(success=False, error="Refusing to move or copy an entire allowed root.")
        if dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            return FileResult(success=False, error=f"'{dst}' already exists; not overwriting.")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(src), str(dst))
            elif src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError as exc:
            return FileResult(success=False, error=f"Could not {'move' if move else 'copy'}: {exc}")
        return FileResult(success=True, content=f"{'Moved' if move else 'Copied'} {src} -> {dst}")

    def delete_file(self, path: str) -> FileResult:
        try:
            resolved = self._guard.resolve(path, must_exist=True)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        if not resolved.is_file():
            return FileResult(success=False, error=f"'{resolved}' is not a file.")

        try:
            resolved.unlink()
        except OSError as exc:
            return FileResult(success=False, error=f"Could not delete '{resolved}': {exc}")

        return FileResult(success=True, content=f"Deleted {resolved}")
