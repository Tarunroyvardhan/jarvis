"""
File intelligence — find, read, search, list, and (with confirmation)
delete files, all restricted to configured allowed directories via
PathGuard. No operation here ever touches a path outside those roots.

PDF/DOCX text extraction uses pypdf/python-docx if installed (the
`files` extra); if not installed, reading those formats fails with a
clear message rather than a raw ImportError, same pattern as the voice
modules' optional dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.security.path_guard import PathAccessError, PathGuard

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv",
    ".html", ".css", ".xml", ".log", ".ini", ".cfg", ".toml",
}


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


class FileIntelligenceService:
    def __init__(self, path_guard: PathGuard) -> None:
        self._guard = path_guard

    def _entry(self, path: Path) -> FileEntry:
        stat = path.stat()
        return FileEntry(
            path=str(path),
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )

    def find_files(self, query: str, directory: str | None = None, limit: int = 20) -> FileResult:
        try:
            root = self._guard.resolve(directory, must_exist=True) if directory else None
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        roots = [root] if root else self._guard.allowed_roots
        matches: list[FileEntry] = []
        query_lower = query.lower()

        try:
            for search_root in roots:
                for path in search_root.rglob("*"):
                    if path.is_file() and query_lower in path.name.lower():
                        matches.append(self._entry(path))
                        if len(matches) >= limit:
                            return FileResult(success=True, files=matches)
        except OSError as exc:
            return FileResult(success=False, error=f"Search failed: {exc}")

        return FileResult(success=True, files=matches)

    def list_recent_files(self, directory: str | None = None, limit: int = 10) -> FileResult:
        try:
            root = self._guard.resolve(directory, must_exist=True) if directory else None
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        roots = [root] if root else self._guard.allowed_roots
        all_files: list[Path] = []
        try:
            for search_root in roots:
                all_files.extend(p for p in search_root.rglob("*") if p.is_file())
        except OSError as exc:
            return FileResult(success=False, error=f"Listing failed: {exc}")

        all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        entries = [self._entry(p) for p in all_files[:limit]]
        return FileResult(success=True, files=entries)

    def read_file(self, path: str) -> FileResult:
        try:
            resolved = self._guard.resolve(path, must_exist=True)
            self._guard.check_readable_size(resolved)
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        if not resolved.is_file():
            return FileResult(success=False, error=f"'{resolved}' is not a file.")

        suffix = resolved.suffix.lower()
        try:
            if suffix == ".pdf":
                content = self._read_pdf(resolved)
            elif suffix == ".docx":
                content = self._read_docx(resolved)
            elif suffix in TEXT_EXTENSIONS or not suffix:
                content = resolved.read_text(encoding="utf-8", errors="replace")
            else:
                return FileResult(
                    success=False,
                    error=f"Unsupported file type '{suffix}'. Supported: text files, .pdf, .docx",
                )
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
            root = self._guard.resolve(directory, must_exist=True) if directory else None
        except PathAccessError as exc:
            return FileResult(success=False, error=str(exc))

        roots = [root] if root else self._guard.allowed_roots
        query_lower = query.lower()
        matches: list[dict] = []

        for search_root in roots:
            for path in search_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query_lower in line.lower():
                        matches.append(
                            {"path": str(path), "line": line_number, "text": line.strip()}
                        )
                        if len(matches) >= limit:
                            return FileResult(success=True, matches=matches)

        return FileResult(success=True, matches=matches)

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
